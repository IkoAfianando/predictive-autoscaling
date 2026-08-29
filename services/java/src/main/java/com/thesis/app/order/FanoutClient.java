package com.thesis.app.order;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import com.thesis.app.config.AppProperties;

/**
 */
@Component
@ConditionalOnProperty(name = "app.service-name", havingValue = "order")
public class FanoutClient {

    public static class UpstreamUnavailableException extends RuntimeException {
        public UpstreamUnavailableException(String msg, Throwable cause) { super(msg, cause); }
    }

    private final RestClient http;
    private final String userServiceUrl;
    private final String productServiceUrl;

    public FanoutClient(RestClient http, AppProperties props) {
        this.http = http;
        this.userServiceUrl = props.getUserServiceUrl();
        this.productServiceUrl = props.getProductServiceUrl();
    }

    public boolean userExists(long userId) {
        return exists(userServiceUrl + "/users/" + userId, "user");
    }

    public boolean productExists(long productId) {
        return exists(productServiceUrl + "/products/" + productId, "product");
    }

    private boolean exists(String url, String what) {
        try {
            http.get().uri(url).retrieve().toBodilessEntity();
            return true; // 2xx
        } catch (RestClientResponseException e) {
            if (e.getStatusCode().value() == 404) {
                return false;
            }
            throw new UpstreamUnavailableException(
                    what + " service returned " + e.getStatusCode().value(), e);
        } catch (Exception e) {
            throw new UpstreamUnavailableException(what + " service unreachable", e);
        }
    }
}
