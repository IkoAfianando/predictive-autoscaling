package com.thesis.app.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 */
@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private String serviceName = "user";   // user | product | order
    private String stackName = "java";      // fixed for this stack
    private int bcryptCost = 10;
    private int dbPoolMax = 20;
    private int cacheTtlSeconds = 30;
    private String databaseUrl = "postgres://appuser:appsecret@localhost:5432/java_db";
    private String redisUrl = "redis://localhost:6379";
    private String userServiceUrl = "http://java-user:8080";
    private String productServiceUrl = "http://java-product:8080";
    private long fanoutTimeoutMs = 5000;
    private long readinessTimeoutMs = 30000;

    public String getServiceName() { return serviceName; }
    public void setServiceName(String v) { this.serviceName = v; }

    public String getStackName() { return stackName; }
    public void setStackName(String v) { this.stackName = v; }

    public int getBcryptCost() { return bcryptCost; }
    public void setBcryptCost(int v) { this.bcryptCost = v; }

    public int getDbPoolMax() { return dbPoolMax; }
    public void setDbPoolMax(int v) { this.dbPoolMax = v; }

    public int getCacheTtlSeconds() { return cacheTtlSeconds; }
    public void setCacheTtlSeconds(int v) { this.cacheTtlSeconds = v; }

    public String getDatabaseUrl() { return databaseUrl; }
    public void setDatabaseUrl(String v) { this.databaseUrl = v; }

    public String getRedisUrl() { return redisUrl; }
    public void setRedisUrl(String v) { this.redisUrl = v; }

    public String getUserServiceUrl() { return userServiceUrl; }
    public void setUserServiceUrl(String v) { this.userServiceUrl = v; }

    public String getProductServiceUrl() { return productServiceUrl; }
    public void setProductServiceUrl(String v) { this.productServiceUrl = v; }

    public long getFanoutTimeoutMs() { return fanoutTimeoutMs; }
    public void setFanoutTimeoutMs(long v) { this.fanoutTimeoutMs = v; }

    public long getReadinessTimeoutMs() { return readinessTimeoutMs; }
    public void setReadinessTimeoutMs(long v) { this.readinessTimeoutMs = v; }
}
