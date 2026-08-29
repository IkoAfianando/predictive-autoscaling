package com.thesis.app.product;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

/**
 */
@RestController
@RequestMapping("/products")
@ConditionalOnProperty(name = "app.service-name", havingValue = "product")
public class ProductController {

    public record ProductRequest(@NotBlank String name, @NotNull BigDecimal price) {}

    private final ProductRepository repo;
    private final ProductCache cache;

    public ProductController(ProductRepository repo, ProductCache cache) {
        this.repo = repo;
        this.cache = cache;
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> getById(@PathVariable long id) {
        Optional<ProductRepository.ProductRow> cached = cache.get(id);
        if (cached.isPresent()) {
            return ResponseEntity.ok(toBody(cached.get()));
        }
        Optional<ProductRepository.ProductRow> fromDb = repo.findById(id);
        if (fromDb.isEmpty()) {
            return ResponseEntity.status(404).body(Map.of("error", "product not found"));
        }
        cache.put(fromDb.get());
        return ResponseEntity.ok(toBody(fromDb.get()));
    }

    @PostMapping
    public ResponseEntity<?> create(@Valid @RequestBody ProductRequest req) {
        long id = repo.insert(req.name(), req.price());
        cache.invalidate(id); // keep cache authoritative
        return ResponseEntity.status(201)
                .body(toBody(new ProductRepository.ProductRow(id, req.name(), req.price())));
    }

    @PutMapping("/{id}")
    public ResponseEntity<?> update(@PathVariable long id, @Valid @RequestBody ProductRequest req) {
        int rows = repo.update(id, req.name(), req.price());
        if (rows == 0) {
            return ResponseEntity.status(404).body(Map.of("error", "product not found"));
        }
        cache.invalidate(id);
        return ResponseEntity.ok(toBody(new ProductRepository.ProductRow(id, req.name(), req.price())));
    }

    private static Map<String, Object> toBody(ProductRepository.ProductRow p) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", p.id());
        body.put("name", p.name());
        body.put("price", p.price());
        return body;
    }
}
