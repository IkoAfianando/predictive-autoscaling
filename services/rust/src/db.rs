use std::time::Duration;

use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tokio::time::sleep;

pub async fn init_pool(url: &str, max_connections: u32) -> Result<PgPool, sqlx::Error> {
    let deadline = std::time::Instant::now() + Duration::from_secs(30);
    let mut last_err: Option<sqlx::Error> = None;

    loop {
        match PgPoolOptions::new()
            .max_connections(max_connections)
            .acquire_timeout(Duration::from_secs(5))
            .connect(url)
            .await
        {
            Ok(pool) => {
                tracing::info!("connected to postgres (max_connections={max_connections})");
                return Ok(pool);
            }
            Err(e) => {
                if std::time::Instant::now() >= deadline {
                    return Err(last_err.unwrap_or(e));
                }
                tracing::warn!("postgres not ready, retrying in 1s: {e}");
                last_err = Some(e);
                sleep(Duration::from_secs(1)).await;
            }
        }
    }
}

pub fn is_unique_violation(e: &sqlx::Error) -> bool {
    e.as_database_error()
        .and_then(|db| db.code())
        .map(|c| c == "23505")
        .unwrap_or(false)
}
