package db

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

func Connect(ctx context.Context, databaseURL string, poolMax int) (*sql.DB, error) {
	dbConn, err := sql.Open("pgx", databaseURL)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}

	dbConn.SetMaxOpenConns(poolMax)
	dbConn.SetMaxIdleConns(poolMax)
	dbConn.SetConnMaxLifetime(30 * time.Minute)
	dbConn.SetConnMaxIdleTime(5 * time.Minute)

	if err := retryPing(ctx, dbConn); err != nil {
		_ = dbConn.Close()
		return nil, err
	}
	return dbConn, nil
}

func retryPing(ctx context.Context, dbConn *sql.DB) error {
	deadline := time.Now().Add(30 * time.Second)
	var lastErr error
	for time.Now().Before(deadline) {
		pingCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
		lastErr = dbConn.PingContext(pingCtx)
		cancel()
		if lastErr == nil {
			return nil
		}
		log.Printf("db: waiting for postgres: %v", lastErr)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(1 * time.Second):
		}
	}
	return fmt.Errorf("db: not reachable within startup budget: %w", lastErr)
}

func Migrate(ctx context.Context, dbConn *sql.DB) error {
	const schema = `
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
);`
	if _, err := dbConn.ExecContext(ctx, schema); err != nil {
		return fmt.Errorf("migrate: %w", err)
	}
	return nil
}
