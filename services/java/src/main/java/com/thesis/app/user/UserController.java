package com.thesis.app.user;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.thesis.app.bcrypt.BcryptService;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;

/**
 */
@RestController
@RequestMapping("/users")
@ConditionalOnProperty(name = "app.service-name", havingValue = "user")
public class UserController {

    public record RegisterRequest(@NotBlank String username, @NotBlank String password) {}
    public record LoginRequest(@NotBlank String username, @NotBlank String password) {}

    private final UserRepository repo;
    private final BcryptService bcrypt;

    public UserController(UserRepository repo, BcryptService bcrypt) {
        this.repo = repo;
        this.bcrypt = bcrypt;
    }

    @PostMapping("/register")
    public ResponseEntity<?> register(@Valid @RequestBody RegisterRequest req) {
        String hash = bcrypt.hash(req.password());
        try {
            long id = repo.insert(req.username(), hash);
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("id", id);
            body.put("username", req.username());
            return ResponseEntity.status(201).body(body);
        } catch (DuplicateKeyException e) {
            return ResponseEntity.status(409).body(Map.of("error", "username already exists"));
        }
    }

    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody LoginRequest req) {
        Optional<UserRepository.UserRow> user = repo.findByUsername(req.username());
        if (user.isPresent() && bcrypt.verify(req.password(), user.get().password())) {
            return ResponseEntity.ok(Map.of("token", UUID.randomUUID().toString()));
        }
        return ResponseEntity.status(401).body(Map.of("error", "invalid credentials"));
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> getById(@PathVariable long id) {
        return repo.findById(id)
                .<ResponseEntity<?>>map(u -> {
                    Map<String, Object> body = new LinkedHashMap<>();
                    body.put("id", u.id());
                    body.put("username", u.username());
                    return ResponseEntity.ok(body);
                })
                .orElseGet(() -> ResponseEntity.status(404).body(Map.of("error", "user not found")));
    }
}
