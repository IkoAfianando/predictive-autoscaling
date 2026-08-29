package com.thesis.app.config;

import java.time.Duration;
import java.util.concurrent.ThreadPoolExecutor;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.client.RestClient;

/**
 */
@Configuration
public class BeansConfig {

    @Bean
    public PasswordEncoder passwordEncoder(AppProperties props) {
        return new BCryptPasswordEncoder(props.getBcryptCost());
    }

    /**
     */
    @Bean(name = "bcryptExecutor")
    public ThreadPoolTaskExecutor bcryptExecutor() {
        int size = Math.max(2, Runtime.getRuntime().availableProcessors());
        String override = System.getenv("BCRYPT_MAX_CONCURRENCY");
        if (override != null && !override.isBlank()) {
            try {
                int parsed = Integer.parseInt(override.trim());
                if (parsed >= 1) {
                    size = parsed;
                }
            } catch (NumberFormatException ignored) {
            }
        }
        ThreadPoolTaskExecutor ex = new ThreadPoolTaskExecutor();
        ex.setCorePoolSize(size);
        ex.setMaxPoolSize(size);
        ex.setQueueCapacity(256);
        ex.setThreadNamePrefix("bcrypt-");
        ex.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        ex.initialize();
        return ex;
    }

    @Bean
    public RestClient restClient(AppProperties props) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofMillis(props.getFanoutTimeoutMs()));
        factory.setReadTimeout(Duration.ofMillis(props.getFanoutTimeoutMs()));
        return RestClient.builder().requestFactory(factory).build();
    }
}
