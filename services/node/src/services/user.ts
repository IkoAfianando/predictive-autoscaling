
import { randomUUID } from "node:crypto";
import bcrypt from "bcrypt";
import type { FastifyInstance } from "fastify";
import type { Pool } from "pg";
import type { Config } from "../config";

interface UserRow {
  id: string; // BIGSERIAL comes back as string from pg
  username: string;
  password: string;
}

interface RegisterBody {
  username?: string;
  password?: string;
}

interface LoginBody {
  username?: string;
  password?: string;
}

export function registerUserRoutes(
  app: FastifyInstance,
  pool: Pool,
  cfg: Config,
): void {
  app.post<{ Body: RegisterBody }>("/users/register", async (request, reply) => {
    const { username, password } = request.body ?? {};
    if (!username || !password) {
      return reply.code(400).send({ error: "username and password are required" });
    }

    const hash = await bcrypt.hash(password, cfg.bcryptCost);

    try {
      const { rows } = await pool.query<{ id: string; username: string }>(
        "INSERT INTO users (username, password) VALUES ($1, $2) RETURNING id, username",
        [username, hash],
      );
      const row = rows[0];
      return reply.code(201).send({ id: Number(row.id), username: row.username });
    } catch (err) {
      if ((err as { code?: string }).code === "23505") {
        return reply.code(409).send({ error: "username already exists" });
      }
      throw err;
    }
  });

  app.post<{ Body: LoginBody }>("/users/login", async (request, reply) => {
    const { username, password } = request.body ?? {};
    if (!username || !password) {
      return reply.code(400).send({ error: "username and password are required" });
    }

    const { rows } = await pool.query<UserRow>(
      "SELECT id, username, password FROM users WHERE username = $1",
      [username],
    );
    const user = rows[0];
    if (!user) {
      return reply.code(401).send({ error: "invalid credentials" });
    }

    const ok = await bcrypt.compare(password, user.password);
    if (!ok) {
      return reply.code(401).send({ error: "invalid credentials" });
    }

    return reply.send({ token: randomUUID() });
  });

  app.get<{ Params: { id: string } }>("/users/:id", async (request, reply) => {
    const { rows } = await pool.query<{ id: string; username: string }>(
      "SELECT id, username FROM users WHERE id = $1",
      [request.params.id],
    );
    const user = rows[0];
    if (!user) {
      return reply.code(404).send({ error: "not found" });
    }
    return reply.send({ id: Number(user.id), username: user.username });
  });
}
