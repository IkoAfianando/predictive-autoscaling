package com.thesis.app.health;

import javax.sql.DataSource;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import com.thesis.app.config.AppProperties;

/**
 */
@Component
public class StartupRunner implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(StartupRunner.class);

    private static final String DDL = """
        CREATE TABLE IF NOT EXISTS users (
          id         BIGSERIAL PRIMARY KEY,
          username   VARCHAR(255) UNIQUE NOT NULL,
          password   VARCHAR(255) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS products (
          id         BIGSERIAL PRIMARY KEY,
          name       VARCHAR(255) NOT NULL,
          price      NUMERIC(12,2) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS orders (
          id         BIGSERIAL PRIMARY KEY,
          user_id    BIGINT NOT NULL,
          product_id BIGINT NOT NULL,
          qty        INT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """;

    private final DataSource dataSource;
    private final StringRedisTemplate redis;
    private final Readiness readiness;
    private final AppProperties props;

    public StartupRunner(DataSource dataSource, StringRedisTemplate redis,
                         Readiness readiness, AppProperties props) {
        this.dataSource = dataSource;
        this.redis = redis;
        this.readiness = readiness;
        this.props = props;
    }

    @Override
    public void run(ApplicationArguments args) {
        long deadline = System.currentTimeMillis() + props.getReadinessTimeoutMs();
        JdbcTemplate jdbc = new JdbcTemplate(dataSource);

        while (System.currentTimeMillis() < deadline) {
            try {
                jdbc.queryForObject("SELECT 1", Integer.class);
                redis.getConnectionFactory().getConnection().ping();
                jdbc.execute(DDL);
                readiness.markReady();
                log.info("Startup readiness OK: DB + Redis reachable, schema ensured (service={}, stack={})",
                        props.getServiceName(), props.getStackName());
                return;
            } catch (Exception e) {
                log.warn("Waiting for DB/Redis: {}", e.getMessage());
                try {
                    Thread.sleep(1500);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
        log.error("DB/Redis not reachable within {} ms — exiting.", props.getReadinessTimeoutMs());
        System.exit(1);
    }
}
