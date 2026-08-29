package com.thesis.app.user;

import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class UserRepository {

    public record UserRow(long id, String username, String password) {}

    private final JdbcTemplate jdbc;

    public UserRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(String username, String passwordHash) {
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO users (username, password) VALUES (?, ?)",
                    new String[]{"id"});
            ps.setString(1, username);
            ps.setString(2, passwordHash);
            return ps;
        }, keys);
        return keys.getKey().longValue();
    }

    public Optional<UserRow> findById(long id) {
        return jdbc.query(
                "SELECT id, username, password FROM users WHERE id = ?",
                rs -> rs.next()
                        ? Optional.of(new UserRow(rs.getLong("id"), rs.getString("username"), rs.getString("password")))
                        : Optional.empty(),
                id);
    }

    public Optional<UserRow> findByUsername(String username) {
        return jdbc.query(
                "SELECT id, username, password FROM users WHERE username = ?",
                rs -> rs.next()
                        ? Optional.of(new UserRow(rs.getLong("id"), rs.getString("username"), rs.getString("password")))
                        : Optional.empty(),
                username);
    }
}
