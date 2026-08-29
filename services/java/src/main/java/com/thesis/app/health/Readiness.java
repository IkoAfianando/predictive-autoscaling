package com.thesis.app.health;

import java.util.concurrent.atomic.AtomicBoolean;

import org.springframework.stereotype.Component;

@Component
public class Readiness {
    private final AtomicBoolean ready = new AtomicBoolean(false);

    public boolean isReady() { return ready.get(); }
    public void markReady() { ready.set(true); }
}
