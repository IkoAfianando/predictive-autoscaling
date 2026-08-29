mod cache;
mod config;
mod db;
mod error;
mod metrics;
mod order;
mod product;
mod state;
mod user;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::get;
use axum::{Json, Router};
use serde_json::json;
use std::time::Duration;
use tokio::net::TcpListener;

use crate::config::Config;
use crate::state::AppState;

async fn health(State(st): State<AppState>) -> impl IntoResponse {
    let db_ok = sqlx::query("SELECT 1").execute(&st.pool).await.is_ok();
    let redis_ok = st.cache.ping().await.is_ok();

    if db_ok && redis_ok {
        (StatusCode::OK, Json(json!({ "status": "ok" })))
    } else {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({ "status": "degraded", "db": db_ok, "redis": redis_ok })),
        )
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let cfg = Config::from_env();
    tracing::info!(
        "starting {} service (stack={}, port={})",
        cfg.service,
        cfg.stack,
        cfg.port
    );

    metrics::register_process_metrics();

    let pool = db::init_pool(&cfg.database_url, cfg.db_pool_max)
        .await
        .expect("failed to connect to postgres within 30s");
    let cache = cache::Cache::connect(&cfg.redis_url, &cfg.stack)
        .await
        .expect("failed to connect to redis within 30s");

    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .expect("failed to build reqwest client");

    let state = AppState::new(&cfg, pool, cache, http);

    let service_router = match cfg.service.as_str() {
        "user" => user::router(),
        "product" => product::router(),
        "order" => order::router(),
        other => panic!("unknown SERVICE_NAME '{other}' (expected user|product|order)"),
    };

    let app: Router = service_router
        .route("/health", get(health))
        .route("/metrics", get(metrics::metrics_handler))
        .layer(axum::middleware::from_fn(metrics::track_metrics))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", cfg.port);
    let listener = TcpListener::bind(&addr)
        .await
        .unwrap_or_else(|e| panic!("failed to bind {addr}: {e}"));
    tracing::info!("listening on {addr}");

    axum::serve(listener, app)
        .await
        .expect("server error");
}
