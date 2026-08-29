
import type { FastifyInstance } from "fastify";
import type { Pool } from "pg";
import type Redis from "ioredis";
import type { Config } from "../config";
import { productKey } from "../cache";

interface ProductRow {
  id: string; // BIGSERIAL -> string
  name: string;
  price: string; // NUMERIC -> string
}

interface Product {
  id: number;
  name: string;
  price: number;
}

interface CreateBody {
  name?: string;
  price?: number | string;
}

interface UpdateBody {
  name?: string;
  price?: number | string;
}

function toProduct(row: ProductRow): Product {
  return { id: Number(row.id), name: row.name, price: Number(row.price) };
}

export function registerProductRoutes(
  app: FastifyInstance,
  pool: Pool,
  redis: Redis,
  cfg: Config,
): void {
  app.get<{ Params: { id: string } }>("/products/:id", async (request, reply) => {
    const { id } = request.params;
    const key = productKey(cfg.stackName, id);

    const cached = await redis.get(key);
    if (cached !== null) {
      reply.header("x-cache", "hit");
      return reply.send(JSON.parse(cached) as Product);
    }

    const { rows } = await pool.query<ProductRow>(
      "SELECT id, name, price FROM products WHERE id = $1",
      [id],
    );
    const row = rows[0];
    if (!row) {
      return reply.code(404).send({ error: "not found" });
    }

    const product = toProduct(row);
    await redis.set(key, JSON.stringify(product), "EX", cfg.cacheTtlSeconds);
    reply.header("x-cache", "miss");
    return reply.send(product);
  });

  app.post<{ Body: CreateBody }>("/products", async (request, reply) => {
    const { name, price } = request.body ?? {};
    if (name === undefined || price === undefined) {
      return reply.code(400).send({ error: "name and price are required" });
    }

    const { rows } = await pool.query<ProductRow>(
      "INSERT INTO products (name, price) VALUES ($1, $2) RETURNING id, name, price",
      [name, price],
    );
    const product = toProduct(rows[0]);
    await redis.del(productKey(cfg.stackName, product.id));
    return reply.code(201).send(product);
  });

  app.put<{ Params: { id: string }; Body: UpdateBody }>(
    "/products/:id",
    async (request, reply) => {
      const { id } = request.params;
      const { name, price } = request.body ?? {};
      if (name === undefined && price === undefined) {
        return reply.code(400).send({ error: "name or price is required" });
      }

      const { rows } = await pool.query<ProductRow>(
        `UPDATE products
            SET name = COALESCE($2, name),
                price = COALESCE($3, price)
          WHERE id = $1
      RETURNING id, name, price`,
        [id, name ?? null, price ?? null],
      );
      const row = rows[0];
      if (!row) {
        return reply.code(404).send({ error: "not found" });
      }

      await redis.del(productKey(cfg.stackName, id));
      return reply.send(toProduct(row));
    },
  );
}
