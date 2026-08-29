
import type { FastifyInstance } from "fastify";
import type { Pool } from "pg";
import type { Config } from "../config";

interface OrderRow {
  id: string;
  user_id: string;
  product_id: string;
  qty: number;
}

interface Order {
  id: number;
  user_id: number;
  product_id: number;
  qty: number;
}

interface CreateBody {
  user_id?: number | string;
  product_id?: number | string;
  qty?: number | string;
}

function toOrder(row: OrderRow): Order {
  return {
    id: Number(row.id),
    user_id: Number(row.user_id),
    product_id: Number(row.product_id),
    qty: row.qty,
  };
}

async function exists(url: string, timeoutMs: number): Promise<boolean> {
  try {
    const res = await fetch(url, {
      method: "GET",
      signal: AbortSignal.timeout(timeoutMs),
    });
    await res.arrayBuffer().catch(() => undefined);
    return res.ok;
  } catch {
    return false;
  }
}

export function registerOrderRoutes(
  app: FastifyInstance,
  pool: Pool,
  cfg: Config,
): void {
  app.post<{ Body: CreateBody }>("/orders", async (request, reply) => {
    const { user_id, product_id, qty } = request.body ?? {};
    if (user_id === undefined || product_id === undefined || qty === undefined) {
      return reply
        .code(400)
        .send({ error: "user_id, product_id and qty are required" });
    }

    const userUrl = `${cfg.userServiceUrl}/users/${user_id}`;
    const productUrl = `${cfg.productServiceUrl}/products/${product_id}`;

    const [userOk, productOk] = await Promise.all([
      exists(userUrl, cfg.fanoutTimeoutMs),
      exists(productUrl, cfg.fanoutTimeoutMs),
    ]);

    if (!userOk) {
      return reply.code(400).send({ error: "user does not exist" });
    }
    if (!productOk) {
      return reply.code(400).send({ error: "product does not exist" });
    }

    const { rows } = await pool.query<OrderRow>(
      `INSERT INTO orders (user_id, product_id, qty)
       VALUES ($1, $2, $3)
       RETURNING id, user_id, product_id, qty`,
      [user_id, product_id, qty],
    );
    return reply.code(201).send(toOrder(rows[0]));
  });

  app.get<{ Params: { id: string } }>("/orders/:id", async (request, reply) => {
    const { rows } = await pool.query<OrderRow>(
      "SELECT id, user_id, product_id, qty FROM orders WHERE id = $1",
      [request.params.id],
    );
    const row = rows[0];
    if (!row) {
      return reply.code(404).send({ error: "not found" });
    }
    return reply.send(toOrder(row));
  });
}
