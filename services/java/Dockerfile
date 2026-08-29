# syntax=docker/dockerfile:1

# ---- Build stage: compile + package the fat jar with Java 25 ----
FROM maven:3.9-eclipse-temurin-25 AS build
WORKDIR /build

# Cache dependencies first for faster rebuilds.
COPY pom.xml .
RUN mvn -q -B -DskipTests dependency:go-offline

COPY src ./src
RUN mvn -q -B -DskipTests package

# ---- Runtime stage: small JRE, non-root ----
FROM eclipse-temurin:25-jre-jammy AS runtime

# curl for the container HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user.
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app

COPY --from=build /build/target/app.jar /app/app.jar
RUN chown -R app:app /app
USER app

# One image, parameterized by SERVICE_NAME (user | product | order).
ENV SERVICE_NAME=user \
    STACK_NAME=java \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=40s --retries=5 \
    CMD curl -fsS "http://localhost:${PORT}/health" || exit 1

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
