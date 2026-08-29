package com.thesis.app.bcrypt;

import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;

import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

/**
 */
@Service
public class BcryptService {

    private final PasswordEncoder encoder;
    private final ThreadPoolTaskExecutor executor;

    public BcryptService(PasswordEncoder encoder, ThreadPoolTaskExecutor bcryptExecutor) {
        this.encoder = encoder;
        this.executor = bcryptExecutor;
    }

    public String hash(String raw) {
        return await(executor.submit(() -> encoder.encode(raw)));
    }

    public boolean verify(String raw, String hash) {
        return await(executor.submit(() -> encoder.matches(raw, hash)));
    }

    private static <T> T await(Future<T> future) {
        try {
            return future.get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("bcrypt task interrupted", e);
        } catch (ExecutionException e) {
            throw new IllegalStateException("bcrypt task failed", e.getCause());
        }
    }
}
