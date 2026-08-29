package com.thesis.app.product;

import java.time.Duration;
import java.util.Optional;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.thesis.app.config.AppProperties;

/**
 */
@Component
@ConditionalOnProperty(name = "app.service-name", havingValue = "product")
public class ProductCache {

    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;
    private final Duration ttl;
    private final String keyPrefix;

    public ProductCache(StringRedisTemplate redis, ObjectMapper mapper, AppProperties props) {
        this.redis = redis;
        this.mapper = mapper;
        this.ttl = Duration.ofSeconds(props.getCacheTtlSeconds());
        this.keyPrefix = props.getStackName() + ":product:";
    }

    private String key(long id) {
        return keyPrefix + id;
    }

    public Optional<ProductRepository.ProductRow> get(long id) {
        String json = redis.opsForValue().get(key(id));
        if (json == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(mapper.readValue(json, ProductRepository.ProductRow.class));
        } catch (Exception e) {
            return Optional.empty();
        }
    }

    public void put(ProductRepository.ProductRow row) {
        try {
            redis.opsForValue().set(key(row.id()), mapper.writeValueAsString(row), ttl);
        } catch (Exception e) {
        }
    }

    public void invalidate(long id) {
        redis.delete(key(id));
    }
}
