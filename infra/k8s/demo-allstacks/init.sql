-- =============================================================================
-- init.sql — PostgreSQL 15 bootstrap for the predictive-autoscaling-thesis.
--
-- Runs once from postgres:15 docker-entrypoint (/docker-entrypoint-initdb.d) and
-- is also reused as a ConfigMap for the Kubernetes postgres pod.
--
-- Creates one database per backend stack (go_db, rust_db, java_db, node_db) with
-- identical table structure (SPEC §3) so the cross-stack comparison is isolated
-- but apples-to-apples. Fully idempotent: safe to re-run.
--
-- Executed as the superuser (POSTGRES_USER = appuser). All objects are owned by
-- appuser so the services (which connect as appuser) can read/write everything.
-- =============================================================================

-- --- Create the four per-stack databases idempotently -----------------------
-- CREATE DATABASE cannot run inside a transaction or an IF NOT EXISTS clause,
-- so we use the psql \gexec trick: build the statement only when it is missing.

SELECT 'CREATE DATABASE go_db'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'go_db')\gexec

SELECT 'CREATE DATABASE rust_db'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'rust_db')\gexec

SELECT 'CREATE DATABASE java_db'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'java_db')\gexec

SELECT 'CREATE DATABASE node_db'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'node_db')\gexec

-- --- Shared table DDL, applied to every database ----------------------------
-- CREATE TABLE IF NOT EXISTS keeps this idempotent on re-run.

\set ddl_users     'CREATE TABLE IF NOT EXISTS users ( id BIGSERIAL PRIMARY KEY, username VARCHAR(255) UNIQUE NOT NULL, password VARCHAR(255) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now() );'
\set ddl_products  'CREATE TABLE IF NOT EXISTS products ( id BIGSERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL, price NUMERIC(12,2) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now() );'
\set ddl_orders    'CREATE TABLE IF NOT EXISTS orders ( id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, product_id BIGINT NOT NULL, qty INT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now() );'

\c go_db
:ddl_users
:ddl_products
:ddl_orders

\c rust_db
:ddl_users
:ddl_products
:ddl_orders

\c java_db
:ddl_users
:ddl_products
:ddl_orders

\c node_db
:ddl_users
:ddl_products
:ddl_orders
