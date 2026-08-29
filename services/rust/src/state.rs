use sqlx::PgPool;

use crate::cache::Cache;
use crate::config::Config;

#[derive(Clone)]
pub struct AppState {
    pub pool: PgPool,
    pub cache: Cache,
    pub http: reqwest::Client,
    pub bcrypt_cost: u32,
    pub cache_ttl: u64,
    pub user_service_url: String,
    pub product_service_url: String,
}

impl AppState {
    pub fn new(cfg: &Config, pool: PgPool, cache: Cache, http: reqwest::Client) -> Self {
        AppState {
            pool,
            cache,
            http,
            bcrypt_cost: cfg.bcrypt_cost,
            cache_ttl: cfg.cache_ttl,
            user_service_url: cfg.user_service_url.trim_end_matches('/').to_string(),
            product_service_url: cfg.product_service_url.trim_end_matches('/').to_string(),
        }
    }
}
