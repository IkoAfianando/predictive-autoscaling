
import Redis from "ioredis";
import type { Config } from "./config";

export function createRedis(cfg: Config): Redis {
  return new Redis(cfg.redisUrl, {
    lazyConnect: true,
    maxRetriesPerRequest: 2,
    enableReadyCheck: true,
  });
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 */
export async function connectWithRetry(
  redis: Redis,
  log: (msg: string) => void,
  maxMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + maxMs;
  let attempt = 0;
  while (true) {
    attempt += 1;
    try {
      if (redis.status !== "ready") {
        if (redis.status === "wait" || redis.status === "end") {
          await redis.connect();
        }
      }
      await redis.ping();
      log(`cache: connected (attempt ${attempt})`);
      return;
    } catch (err) {
      if (Date.now() >= deadline) {
        throw new Error(
          `cache: could not connect within ${maxMs}ms: ${(err as Error).message}`,
        );
      }
      log(
        `cache: not ready (attempt ${attempt}), retrying: ${(err as Error).message}`,
      );
      await sleep(1000);
    }
  }
}

export async function cacheHealthy(redis: Redis): Promise<boolean> {
  try {
    const pong = await redis.ping();
    return pong === "PONG";
  } catch {
    return false;
  }
}

export function productKey(stack: string, id: string | number): string {
  return `${stack}:product:${id}`;
}
