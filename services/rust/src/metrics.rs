use std::env;
use std::time::Instant;

use axum::extract::MatchedPath;
use axum::http::header::CONTENT_TYPE;
use axum::http::Request;
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use once_cell::sync::Lazy;
use prometheus::{Encoder, HistogramOpts, HistogramVec, TextEncoder};

pub const BUCKETS: [f64; 72] = [
    0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009, //
    0.010, 0.015, 0.020, 0.025, 0.030, 0.035, 0.040, 0.045, 0.050, //
    0.060, 0.070, 0.080, 0.090, 0.100, 0.125, 0.150, 0.175, 0.200, //
    0.250, 0.300, 0.350, 0.400, 0.450, 0.500, 0.600, 0.700, 0.800, //
    0.900, 1.000, 1.250, 1.500, 1.750, 2.000, 2.500, 3.000, 3.500, //
    4.000, 4.500, 5.000, 6.000, 7.000, 8.000, 9.000, 10.000, 12.500, //
    15.000, 17.500, 20.000, 22.500, 25.000, 27.500, 30.000, 35.000, //
    40.000, 45.000, 50.000, 55.000, 60.000, 70.000, 80.000, 90.000, //
    100.000, 120.000,
];

static SERVICE_LABEL: Lazy<String> =
    Lazy::new(|| env::var("SERVICE_NAME").unwrap_or_else(|_| "user".to_string()));

static STACK_LABEL: Lazy<String> =
    Lazy::new(|| env::var("STACK_NAME").unwrap_or_else(|_| "rust".to_string()));

pub static HTTP_HISTOGRAM: Lazy<HistogramVec> = Lazy::new(|| {
    let opts = HistogramOpts::new(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
    )
    .buckets(BUCKETS.to_vec());
    prometheus::register_histogram_vec!(
        opts,
        &["service", "stack", "method", "route", "status"]
    )
    .expect("failed to register http_request_duration_seconds")
});

pub fn register_process_metrics() {
    #[cfg(target_os = "linux")]
    {
        let collector = prometheus::process_collector::ProcessCollector::for_self();
        let _ = prometheus::default_registry().register(Box::new(collector));
    }
    Lazy::force(&HTTP_HISTOGRAM);
}

pub async fn track_metrics(req: Request<axum::body::Body>, next: Next) -> Response {
    let method = req.method().as_str().to_owned();
    let route = req
        .extensions()
        .get::<MatchedPath>()
        .map(|p| p.as_str().to_owned())
        .unwrap_or_else(|| req.uri().path().to_owned());

    let start = Instant::now();
    let response = next.run(req).await;
    let elapsed = start.elapsed().as_secs_f64();
    let status = response.status().as_u16().to_string();

    HTTP_HISTOGRAM
        .with_label_values(&[
            SERVICE_LABEL.as_str(),
            STACK_LABEL.as_str(),
            &method,
            &route,
            &status,
        ])
        .observe(elapsed);

    response
}

pub async fn metrics_handler() -> impl IntoResponse {
    let encoder = TextEncoder::new();
    let metric_families = prometheus::gather();
    let mut buffer = Vec::new();
    if let Err(e) = encoder.encode(&metric_families, &mut buffer) {
        return (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            format!("metrics encode error: {e}"),
        )
            .into_response();
    }
    ([(CONTENT_TYPE, encoder.format_type())], buffer).into_response()
}
