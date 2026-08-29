use std::env;

#[derive(Clone, Debug)]
pub struct Config {
    pub service: String,
    pub stack: String,
    pub port: u16,
    pub database_url: String,
    pub redis_url: String,
    pub bcrypt_cost: u32,
    pub db_pool_max: u32,
    pub cache_ttl: u64,
    pub user_service_url: String,
    pub product_service_url: String,
}

fn env_or(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn parse_or<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

impl Config {
    pub fn from_env() -> Self {
        let service = env_or("SERVICE_NAME", "user");
        let stack = env_or("STACK_NAME", "rust");
        Config {
            service,
            stack,
            port: parse_or("PORT", 8080u16),
            database_url: env_or(
                "DATABASE_URL",
                "postgres://appuser:appsecret@postgres:5432/rust_db",
            ),
            redis_url: env_or("REDIS_URL", "redis://redis:6379"),
            bcrypt_cost: parse_or("BCRYPT_COST", 10u32),
            db_pool_max: parse_or("DB_POOL_MAX", 20u32),
            cache_ttl: parse_or("CACHE_TTL_SECONDS", 30u64),
            user_service_url: env_or("USER_SERVICE_URL", "http://rust-user:8080"),
            product_service_url: env_or("PRODUCT_SERVICE_URL", "http://rust-product:8080"),
        }
    }
}
