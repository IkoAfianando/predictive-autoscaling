# Multi-stage build for the Node.js (Fastify + TypeScript) stack.
# One image parameterized by SERVICE_NAME (user|product|order) at runtime.
#
# Both stages use the same Debian base so bcrypt's native addon, compiled in the
# build stage, is ABI-compatible with the runtime stage.

# ---- build stage -------------------------------------------------------------
FROM node:20-bookworm-slim AS build
WORKDIR /app

# Build toolchain for bcrypt's native addon.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json* ./
# Install all deps (incl. dev) so tsc is available and native modules compile.
RUN npm install

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# Drop dev dependencies for the runtime image (keeps native builds intact).
RUN npm prune --omit=dev

# ---- runtime stage -----------------------------------------------------------
FROM node:20-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

# The node:20 image already ships a non-root "node" user.
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --from=build --chown=node:node /app/package.json ./package.json

USER node

# SERVICE_NAME selects which routes to register (user|product|order).
ENV SERVICE_NAME=user
ENV STACK_NAME=node
ENV PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||8080)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "dist/index.js"]
