package com.thesis.app.health;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 */
@RestController
public class HealthController {

    private final Readiness readiness;

    public HealthController(Readiness readiness) {
        this.readiness = readiness;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        if (readiness.isReady()) {
            return ResponseEntity.ok(Map.of("status", "ok"));
        }
        return ResponseEntity.status(503).body(Map.of("status", "starting"));
    }
}
