use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::json;

use crate::error::AppError;
use crate::state::AppState;

#[derive(sqlx::FromRow)]
struct OrderRow {
    id: i64,
    user_id: i64,
    product_id: i64,
    qty: i32,
}

impl OrderRow {
    fn to_json(&self) -> serde_json::Value {
        json!({
            "id": self.id,
            "user_id": self.user_id,
            "product_id": self.product_id,
            "qty": self.qty,
        })
    }
}

#[derive(Deserialize)]
pub struct OrderInput {
    user_id: i64,
    product_id: i64,
    qty: i32,
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/orders", post(create_order))
        .route("/orders/:id", get(get_order))
}

async fn create_order(
    State(st): State<AppState>,
    Json(body): Json<OrderInput>,
) -> Result<impl IntoResponse, AppError> {
    let user_url = format!("{}/users/{}", st.user_service_url, body.user_id);
    let product_url = format!("{}/products/{}", st.product_service_url, body.product_id);

    let (user_res, product_res) = tokio::join!(
        st.http.get(&user_url).send(),
        st.http.get(&product_url).send(),
    );

    let user_resp = user_res?;
    if !user_resp.status().is_success() {
        return Err(AppError::new(
            StatusCode::BAD_REQUEST,
            format!("user {} not found", body.user_id),
        ));
    }

    let product_resp = product_res?;
    if !product_resp.status().is_success() {
        return Err(AppError::new(
            StatusCode::BAD_REQUEST,
            format!("product {} not found", body.product_id),
        ));
    }

    let row = sqlx::query_as::<_, OrderRow>(
        "INSERT INTO orders (user_id, product_id, qty) VALUES ($1, $2, $3) \
         RETURNING id, user_id, product_id, qty",
    )
    .bind(body.user_id)
    .bind(body.product_id)
    .bind(body.qty)
    .fetch_one(&st.pool)
    .await?;

    Ok((StatusCode::CREATED, Json(row.to_json())))
}

async fn get_order(
    State(st): State<AppState>,
    Path(id): Path<i64>,
) -> Result<impl IntoResponse, AppError> {
    let row = sqlx::query_as::<_, OrderRow>(
        "SELECT id, user_id, product_id, qty FROM orders WHERE id = $1",
    )
    .bind(id)
    .fetch_optional(&st.pool)
    .await?;

    match row {
        Some(o) => Ok(Json(o.to_json())),
        None => Err(AppError::new(StatusCode::NOT_FOUND, "order not found")),
    }
}
