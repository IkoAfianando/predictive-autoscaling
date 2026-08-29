
import { Pool } from "pg";
import type { PoolConfig } from "pg";
import type { Config } from "./config";

export function createPool(cfg: Config): Pool {
  const poolConfig: PoolConfig = {
    connectionString: cfg.databaseUrl,
    max: cfg.dbPoolMax, // SPEC §2: DB connection pool max = 20
  };
  return new Pool(poolConfig);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 */
export async function connectWithRetry(
  pool: Pool,
  log: (msg: string) => void,
  maxMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + maxMs;
  let attempt = 0;
  while (true) {
    attempt += 1;
    try {
      const client = await pool.connect();
      try {
        await client.query("SELECT 1");
      } finally {
        client.release();
      }
      log(`db: connected (attempt ${attempt})`);
      return;
    } catch (err) {
      if (Date.now() >= deadline) {
        throw new Error(
          `db: could not connect within ${maxMs}ms: ${(err as Error).message}`,
        );
      }
      log(`db: not ready (attempt ${attempt}), retrying: ${(err as Error).message}`);
      await sleep(1000);
    }
  }
}

export async function dbHealthy(pool: Pool): Promise<boolean> {
  try {
    await pool.query("SELECT 1");
    return true;
  } catch {
    return false;
  }
}
