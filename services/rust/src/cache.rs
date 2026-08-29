use std::time::Duration;

use redis::aio::MultiplexedConnection;
use redis::AsyncCommands;
use tokio::time::sleep;

#[derive(Clone)]
pub struct Cache {
    conn: MultiplexedConnection,
    prefix: String,
}

impl Cache {
    pub async fn connect(url: &str, stack: &str) -> Result<Cache, redis::RedisError> {
        let client = redis::Client::open(url)?;
        let deadline = std::time::Instant::now() + Duration::from_secs(30);
        let mut last_err: Option<redis::RedisError> = None;

        loop {
            match client.get_multiplexed_async_connection().await {
                Ok(conn) => {
                    tracing::info!("connected to redis");
                    return Ok(Cache { conn, prefix: format!("{stack}:") });
                }
                Err(e) => {
                    if std::time::Instant::now() >= deadline {
                        return Err(last_err.unwrap_or(e));
                    }
                    tracing::warn!("redis not ready, retrying in 1s: {e}");
                    last_err = Some(e);
                    sleep(Duration::from_secs(1)).await;
                }
            }
        }
    }

    fn key(&self, suffix: &str) -> String {
        format!("{}{}", self.prefix, suffix)
    }

    pub async fn get(&self, suffix: &str) -> Result<Option<String>, redis::RedisError> {
        let mut conn = self.conn.clone();
        conn.get(self.key(suffix)).await
    }

    pub async fn set_ex(
        &self,
        suffix: &str,
        value: &str,
        ttl_seconds: u64,
    ) -> Result<(), redis::RedisError> {
        let mut conn = self.conn.clone();
        conn.set_ex(self.key(suffix), value, ttl_seconds).await
    }

    pub async fn del(&self, suffix: &str) -> Result<(), redis::RedisError> {
        let mut conn = self.conn.clone();
        conn.del::<_, ()>(self.key(suffix)).await
    }

    pub async fn ping(&self) -> Result<(), redis::RedisError> {
        let mut conn = self.conn.clone();
        redis::cmd("PING").query_async::<()>(&mut conn).await
    }
}
