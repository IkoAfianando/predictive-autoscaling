
import {
  Registry,
  Histogram,
  collectDefaultMetrics,
} from "prom-client";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

export const BUCKETS: number[] = [
  0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009,
  0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05,
  0.06, 0.07, 0.08, 0.09, 0.1, 0.125, 0.15, 0.175, 0.2,
  0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8,
  0.9, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5,
  4.0, 4.5, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.5,
  15.0, 17.5, 20.0, 22.5, 25.0, 27.5, 30.0, 35.0,
  40.0, 45.0, 50.0, 55.0, 60.0, 70.0, 80.0, 90.0,
  100.0, 120.0,
];

export const registry = new Registry();

collectDefaultMetrics({ register: registry });

export const httpRequestDuration = new Histogram({
  name: "http_request_duration_seconds",
  help: "HTTP request duration in seconds.",
  labelNames: ["service", "stack", "method", "route", "status"] as const,
  buckets: BUCKETS,
  registers: [registry],
});

const START = Symbol("metrics_start_ns");

interface Timed {
  [START]?: bigint;
}

/**
 */
export function registerMetricsHooks(
  app: FastifyInstance,
  service: string,
  stack: string,
): void {
  app.addHook("onRequest", async (request: FastifyRequest) => {
    (request as unknown as Timed)[START] = process.hrtime.bigint();
  });

  app.addHook(
    "onResponse",
    async (request: FastifyRequest, reply: FastifyReply) => {
      const start = (request as unknown as Timed)[START];
      const seconds =
        start !== undefined
          ? Number(process.hrtime.bigint() - start) / 1e9
          : reply.elapsedTime / 1000;

      const route = request.routeOptions?.url ?? "unmatched";

      httpRequestDuration
        .labels(
          service,
          stack,
          request.method,
          route,
          String(reply.statusCode),
        )
        .observe(seconds);
    },
  );
}
