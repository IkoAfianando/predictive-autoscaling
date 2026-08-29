package com.thesis.app.product;

import java.math.BigDecimal;
import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class ProductRepository {

    public record ProductRow(long id, String name, BigDecimal price) {}

    private final JdbcTemplate jdbc;

    public ProductRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(String name, BigDecimal price) {
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update(con -> {
            var ps = con.prepareStatement(
                    "INSERT INTO products (name, price) VALUES (?, ?)",
                    new String[]{"id"});
            ps.setString(1, name);
            ps.setBigDecimal(2, price);
            return ps;
        }, keys);
        return keys.getKey().longValue();
    }

    public int update(long id, String name, BigDecimal price) {
        return jdbc.update("UPDATE products SET name = ?, price = ? WHERE id = ?", name, price, id);
    }

    public Optional<ProductRow> findById(long id) {
        return jdbc.query(
                "SELECT id, name, price FROM products WHERE id = ?",
                rs -> rs.next()
                        ? Optional.of(new ProductRow(rs.getLong("id"), rs.getString("name"), rs.getBigDecimal("price")))
                        : Optional.empty(),
                id);
    }
}
