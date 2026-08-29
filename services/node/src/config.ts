
export type ServiceName = "user" | "product" | "order";

export interface Config {
  serviceName: ServiceName; // user | product | order
  stackName: string; // go | rust | java | node
  port: number; // internal port, default 8080

  databaseUrl: string;
  redisUrl: string;

  bcryptCost: number; // 10
  dbPoolMax: number; // 20
  cacheTtlSeconds: number; // 30

  userServiceUrl: string;
  productServiceUrl: string;

  fanoutTimeoutMs: number;
}

function getEnv(key: string, def: string): string {
  const v = process.env[key];
  return v !== undefined && v !== "" ? v : def;
}

function getEnvInt(key: string, def: number): number {
  const v = process.env[key];
  if (v !== undefined && v !== "") {
    const n = Number.parseInt(v, 10);
    if (Number.isNaN(n)) {
      console.warn(`config: invalid int for ${key}="${v}", using default ${def}`);
      return def;
    }
    return n;
  }
  return def;
}

export function loadConfig(): Config {
  const stackName = getEnv("STACK_NAME", "node");
  const serviceName = getEnv("SERVICE_NAME", "user") as ServiceName;

  return {
    serviceName,
    stackName,
    port: getEnvInt("PORT", 8080),
    databaseUrl: getEnv(
      "DATABASE_URL",
      `postgres://appuser:appsecret@localhost:5432/${stackName}_db`,
    ),
    redisUrl: getEnv("REDIS_URL", "redis://localhost:6379"),
    bcryptCost: getEnvInt("BCRYPT_COST", 10),
    dbPoolMax: getEnvInt("DB_POOL_MAX", 20),
    cacheTtlSeconds: getEnvInt("CACHE_TTL_SECONDS", 30),
    userServiceUrl: getEnv("USER_SERVICE_URL", `http://${stackName}-user:8080`),
    productServiceUrl: getEnv("PRODUCT_SERVICE_URL", `http://${stackName}-product:8080`),
    fanoutTimeoutMs: getEnvInt("FANOUT_TIMEOUT_MS", 5000),
  };
}
