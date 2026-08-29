package com.thesis.app.order;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fasterxml.jackson.annotation.JsonProperty;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

/**
 */
@RestController
@RequestMapping("/orders")
@ConditionalOnProperty(name = "app.service-name", havingValue = "order")
public class OrderController {

    public record OrderRequest(
            @JsonProperty("user_id") @NotNull Long userId,
            @JsonProperty("product_id") @NotNull Long productId,
            @NotNull @Positive Integer qty) {}

    private final OrderRepository repo;
    private final FanoutClient fanout;

    public OrderController(OrderRepository repo, FanoutClient fanout) {
        this.repo = repo;
        this.fanout = fanout;
    }

    @PostMapping
    public ResponseEntity<?> create(@Valid @RequestBody OrderRequest req) {
        try {
            if (!fanout.userExists(req.userId())) {
                return ResponseEntity.status(400).body(Map.of("error", "user not found"));
            }
            if (!fanout.productExists(req.productId())) {
                return ResponseEntity.status(400).body(Map.of("error", "product not found"));
            }
        } catch (FanoutClient.UpstreamUnavailableException e) {
            return ResponseEntity.status(502).body(Map.of("error", e.getMessage()));
        }

        long id = repo.insert(req.userId(), req.productId(), req.qty());
        return ResponseEntity.status(201).body(toBody(
                new OrderRepository.OrderRow(id, req.userId(), req.productId(), req.qty())));
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> getById(@PathVariable long id) {
        return repo.findById(id)
                .<ResponseEntity<?>>map(o -> ResponseEntity.ok(toBody(o)))
                .orElseGet(() -> ResponseEntity.status(404).body(Map.of("error", "order not found")));
    }

    private static Map<String, Object> toBody(OrderRepository.OrderRow o) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", o.id());
        body.put("user_id", o.userId());
        body.put("product_id", o.productId());
        body.put("qty", o.qty());
        return body;
    }
}
