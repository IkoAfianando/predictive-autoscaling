
import Fastify from "fastify";
import type { FastifyInstance } from "fastify";

import { loadConfig } from "./config";
import { registry, registerMetricsHooks } from "./metrics";
import {
  createPool,
  connectWithRetry as connectDb,
  dbHealthy,
} from "./db";
import {
  createRedis,
  connectWithRetry as connectRedis,
  cacheHealthy,
} from "./cache";
import { registerUserRoutes } from "./services/user";
import { registerProductRoutes } from "./services/product";
import { registerOrderRoutes } from "./services/order";

async function main(): Promise<void> {
  const cfg = loadConfig();

  const app: FastifyInstance = Fastify({
    logger: {
      level: process.env.LOG_LEVEL ?? "info",
    },
    trustProxy: true,
  });

  const log = (msg: string) => app.log.info(msg);

  const pool = createPool(cfg);
  const redis = createRedis(cfg);

  registerMetricsHooks(app, cfg.serviceName, cfg.stackName);

  app.get("/health", async (_request, reply) => {
    const [db, cache] = await Promise.all([dbHealthy(pool), cacheHealthy(redis)]);
    if (db && cache) {
      return reply.send({ status: "ok" });
    }
    return reply.code(503).send({ status: "degraded", db, cache });
  });

  app.get("/metrics", async (_request, reply) => {
    reply.header("Content-Type", registry.contentType);
    return reply.send(await registry.metrics());
  });

  switch (cfg.serviceName) {
    case "user":
      registerUserRoutes(app, pool, cfg);
      break;
    case "product":
      registerProductRoutes(app, pool, redis, cfg);
      break;
    case "order":
      registerOrderRoutes(app, pool, cfg);
      break;
    default:
      throw new Error(
        `unknown SERVICE_NAME "${cfg.serviceName}" (expected user|product|order)`,
      );
  }

  await Promise.all([
    connectDb(pool, log),
    connectRedis(redis, log),
  ]);

  await app.listen({ host: "0.0.0.0", port: cfg.port });
  app.log.info(
    `${cfg.stackName}-${cfg.serviceName} listening on :${cfg.port}`,
  );

  const shutdown = async (signal: string) => {
    app.log.info(`received ${signal}, shutting down`);
    try {
      await app.close();
      await pool.end();
      redis.disconnect();
    } finally {
      process.exit(0);
    }
  };
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((err) => {
  console.error("fatal: failed to start service", err);
  process.exit(1);
});
