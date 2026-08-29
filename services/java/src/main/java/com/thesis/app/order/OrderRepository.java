package com.thesis.app.order;

import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class OrderRepository {

    public record OrderRow(long id, long userId, long productId, int qty) {}

    private final JdbcTemplate jdbc;

    public OrderRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(long userId, long productId, int qty) {
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO orders (user_id, product_id, qty) VALUES (?, ?, ?)",
                    new String[]{"id"});
            ps.setLong(1, userId);
            ps.setLong(2, productId);
            ps.setInt(3, qty);
            return ps;
        }, keys);
        return keys.getKey().longValue();
    }

    public Optional<OrderRow> findById(long id) {
        return jdbc.query(
                "SELECT id, user_id, product_id, qty FROM orders WHERE id = ?",
                rs -> rs.next()
                        ? Optional.of(new OrderRow(
                                rs.getLong("id"), rs.getLong("user_id"),
                                rs.getLong("product_id"), rs.getInt("qty")))
                        : Optional.empty(),
                id);
    }
}
