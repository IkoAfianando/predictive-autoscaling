package com.thesis.app.config;

import java.net.URI;

import javax.sql.DataSource;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.zaxxer.hikari.HikariDataSource;

/**
 */
@Configuration
public class DataSourceConfig {

    @Bean
    public DataSource dataSource(AppProperties props) {
        URI uri = URI.create(props.getDatabaseUrl());

        String host = uri.getHost() != null ? uri.getHost() : "localhost";
        int port = uri.getPort() != -1 ? uri.getPort() : 5432;
        String db = (uri.getPath() != null && uri.getPath().length() > 1)
                ? uri.getPath().substring(1) : "postgres";

        String user = "appuser";
        String pass = "appsecret";
        String userInfo = uri.getUserInfo();
        if (userInfo != null && !userInfo.isEmpty()) {
            int sep = userInfo.indexOf(':');
            if (sep >= 0) {
                user = userInfo.substring(0, sep);
                pass = userInfo.substring(sep + 1);
            } else {
                user = userInfo;
                pass = "";
            }
        }

        String jdbcUrl = "jdbc:postgresql://" + host + ":" + port + "/" + db;

        HikariDataSource ds = new HikariDataSource();
        ds.setJdbcUrl(jdbcUrl);
        ds.setUsername(user);
        ds.setPassword(pass);
        ds.setMaximumPoolSize(props.getDbPoolMax()); // SPEC §2: 20
        ds.setMinimumIdle(2);
        ds.setPoolName("java-" + props.getServiceName() + "-pool");
        ds.setConnectionTimeout(5000);
        ds.setInitializationFailTimeout(-1);
        return ds;
    }
}
