use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::error::AppError;
use crate::state::AppState;

#[derive(sqlx::FromRow)]
struct ProductRow {
    id: i64,
    name: String,
    price: f64,
}

impl ProductRow {
    fn to_json(&self) -> Value {
        json!({ "id": self.id, "name": self.name, "price": self.price })
    }
}

#[derive(Deserialize)]
pub struct ProductInput {
    name: String,
    price: f64,
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/products", post(create_product))
        .route("/products/:id", get(get_product).put(update_product))
}

async fn get_product(
    State(st): State<AppState>,
    Path(id): Path<i64>,
) -> Result<impl IntoResponse, AppError> {
    let cache_key = format!("product:{id}");

    if let Some(cached) = st.cache.get(&cache_key).await? {
        let value: Value = serde_json::from_str(&cached)?;
        return Ok(Json(value));
    }

    let row = sqlx::query_as::<_, ProductRow>(
        "SELECT id, name, price::float8 AS price FROM products WHERE id = $1",
    )
    .bind(id)
    .fetch_optional(&st.pool)
    .await?;

    let Some(product) = row else {
        return Err(AppError::new(StatusCode::NOT_FOUND, "product not found"));
    };

    let body = product.to_json();
    let _ = st
        .cache
        .set_ex(&cache_key, &body.to_string(), st.cache_ttl)
        .await;

    Ok(Json(body))
}

async fn create_product(
    State(st): State<AppState>,
    Json(body): Json<ProductInput>,
) -> Result<impl IntoResponse, AppError> {
    let row = sqlx::query_as::<_, ProductRow>(
        "INSERT INTO products (name, price) VALUES ($1, $2) \
         RETURNING id, name, price::float8 AS price",
    )
    .bind(&body.name)
    .bind(body.price)
    .fetch_one(&st.pool)
    .await?;

    let _ = st.cache.del(&format!("product:{}", row.id)).await;

    Ok((StatusCode::CREATED, Json(row.to_json())))
}

async fn update_product(
    State(st): State<AppState>,
    Path(id): Path<i64>,
    Json(body): Json<ProductInput>,
) -> Result<impl IntoResponse, AppError> {
    let row = sqlx::query_as::<_, ProductRow>(
        "UPDATE products SET name = $1, price = $2 WHERE id = $3 \
         RETURNING id, name, price::float8 AS price",
    )
    .bind(&body.name)
    .bind(body.price)
    .bind(id)
    .fetch_optional(&st.pool)
    .await?;

    let Some(product) = row else {
        return Err(AppError::new(StatusCode::NOT_FOUND, "product not found"));
    };

    let _ = st.cache.del(&format!("product:{id}")).await;

    Ok(Json(product.to_json()))
}
