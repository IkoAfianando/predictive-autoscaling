use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use once_cell::sync::Lazy;
use serde::Deserialize;
use serde_json::json;
use tokio::sync::{Semaphore, SemaphorePermit};
use uuid::Uuid;

use crate::db::is_unique_violation;
use crate::error::AppError;
use crate::state::AppState;

static BCRYPT_SEMAPHORE: Lazy<Option<Semaphore>> = Lazy::new(|| {
    std::env::var("BCRYPT_MAX_CONCURRENCY")
        .ok()
        .and_then(|v| v.trim().parse::<usize>().ok())
        .filter(|&n| n >= 1)
        .map(Semaphore::new)
});

async fn bcrypt_permit() -> Option<SemaphorePermit<'static>> {
    match &*BCRYPT_SEMAPHORE {
        Some(sem) => Some(sem.acquire().await.expect("bcrypt semaphore closed")),
        None => None,
    }
}

#[derive(sqlx::FromRow)]
struct UserRow {
    id: i64,
    username: String,
}

#[derive(sqlx::FromRow)]
struct UserAuthRow {
    password: String,
}

#[derive(Deserialize)]
pub struct Credentials {
    username: String,
    password: String,
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/users/register", post(register))
        .route("/users/login", post(login))
        .route("/users/:id", get(get_user))
}

async fn register(
    State(st): State<AppState>,
    Json(body): Json<Credentials>,
) -> Result<impl IntoResponse, AppError> {
    let cost = st.bcrypt_cost;
    let password = body.password;
    let hash = {
        let _permit = bcrypt_permit().await;
        tokio::task::spawn_blocking(move || bcrypt::hash(password, cost)).await??
    };

    let row = sqlx::query_as::<_, UserRow>(
        "INSERT INTO users (username, password) VALUES ($1, $2) RETURNING id, username",
    )
    .bind(&body.username)
    .bind(&hash)
    .fetch_one(&st.pool)
    .await
    .map_err(|e| {
        if is_unique_violation(&e) {
            AppError::new(StatusCode::CONFLICT, "username already taken")
        } else {
            e.into()
        }
    })?;

    Ok((
        StatusCode::CREATED,
        Json(json!({ "id": row.id, "username": row.username })),
    ))
}

async fn login(
    State(st): State<AppState>,
    Json(body): Json<Credentials>,
) -> Result<impl IntoResponse, AppError> {
    let row = sqlx::query_as::<_, UserAuthRow>("SELECT password FROM users WHERE username = $1")
        .bind(&body.username)
        .fetch_optional(&st.pool)
        .await?;

    let Some(user) = row else {
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "invalid credentials"));
    };

    let password = body.password;
    let hash = user.password;
    let valid = {
        let _permit = bcrypt_permit().await;
        tokio::task::spawn_blocking(move || bcrypt::verify(password, &hash)).await??
    };

    if !valid {
        return Err(AppError::new(StatusCode::UNAUTHORIZED, "invalid credentials"));
    }

    Ok(Json(json!({ "token": Uuid::new_v4().to_string() })))
}

async fn get_user(
    State(st): State<AppState>,
    Path(id): Path<i64>,
) -> Result<impl IntoResponse, AppError> {
    let row = sqlx::query_as::<_, UserRow>("SELECT id, username FROM users WHERE id = $1")
        .bind(id)
        .fetch_optional(&st.pool)
        .await?;

    match row {
        Some(u) => Ok(Json(json!({ "id": u.id, "username": u.username }))),
        None => Err(AppError::new(StatusCode::NOT_FOUND, "user not found")),
    }
}
