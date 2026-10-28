# Observability Plan & Operational Runbook

The observability architecture provides comprehensive visibility into system health, latency, business operations, and errors across the Amrutam Telemedicine modular monolith.

## 1. Structured Logging

Logs are emitted to `stdout` formatted as JSON lines in production (`LOG_FORMAT=json`) and colored structured text in local development (`LOG_FORMAT=console`).

### Log Schema & Trace Correlation
```json
{
  "timestamp": "2026-10-28T12:00:00.123456Z",
  "level": "INFO",
  "service": "Amrutam Telemedicine API",
  "environment": "production",
  "logger": "app.middleware.request",
  "message": "GET /api/v1/bookings -> 200 (42.15 ms)",
  "request_id": "req_01j9a4k7...",
  "correlation_id": "corr_98fbc...",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7"
}
```

### Log Sanitization Rules
- **Credentials & Auth:** Never log passwords, password hashes, JWT tokens, MFA secret seeds, or authentication headers.
- **Protected Health Information (PHI):** Never log medical prescription contents, diagnostic notes, or clinical reason strings.
- **Financial Data:** Never log credit card numbers or CVVs.
- **Recursive Masking:** The `StructuredJsonFormatter` automatically applies `redact_sensitive_data` to scrub nested dictionaries, lists, and extra context fields with `[REDACTED]`.

---

## 2. Prometheus Metrics

Metrics are exposed in standard Prometheus text exposition format (`version=0.0.4; charset=utf-8`) at `GET /metrics` (and `GET /api/v1/metrics`).

### Security & Access Control
- **Environment Setting:** `METRICS_ENABLED=true` (defaults to `true`). If set to `false`, `/metrics` returns `404 Not Found`.
- **Token Protection:** `METRICS_AUTH_TOKEN` (optional). If configured, `/metrics` requires either an `Authorization: Bearer <token>` or an `X-Metrics-Key: <token>` header; unauthorized requests receive `401 Unauthorized`. In Kubernetes, this endpoint should be restricted to the cluster internal scraping subnet via NetworkPolicies.

### Strict Low-Cardinality Rule
**Cardinality Rule:** Labels must be strictly low-cardinality enum values (e.g., HTTP method, route template, status code).
- User IDs, patient emails, resource UUIDs, or timestamps must **never** be used as metric labels.
- `normalize_route_template()` converts dynamic path segments like `/api/v1/bookings/a1b2c3d4-e5f6-4a1b-8c2d-9e0f1a2b3c4d` into bounded templates like `/api/v1/bookings/{id}`.

### Core Metrics Inventory
| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `route`, `status_code` | Total HTTP requests processed across route templates |
| `http_request_duration_seconds` | Histogram | `method`, `route` | Request latency in seconds (buckets: 0.005s to 10.0s) |
| `http_requests_in_flight` | Gauge | *none* | Number of concurrent requests executing |
| `db_pool_size` | Gauge | *none* | Configured SQLAlchemy connection pool capacity |
| `db_pool_checked_in` | Gauge | *none* | Idle database connections available in pool |
| `db_pool_checked_out` | Gauge | *none* | Active database connections checked out by queries |
| `db_query_duration_seconds` | Histogram | `operation` | Database query execution latency by operation (`SELECT`, `INSERT`, etc.) |
| `booking_operations_total` | Counter | `outcome` | Appointment booking outcomes (`success`, `conflict`, `error`) |
| `idempotency_replays_total` | Counter | `outcome` | Idempotency key outcomes (`replayed`, `payload_mismatch`) |
| `outbox_events_lag_seconds` | Gauge | *none* | Age in seconds of oldest pending transactional outbox event |
| `worker_jobs_total` | Counter | `job_type`, `status` | Outbox worker job executions (`processed`, `retried`, `dead_letter`) |
| `payment_transactions_total` | Counter | `provider`, `status` | Payment outcomes (`succeeded`, `failed`, `pending`, `refunded`) |

---

## 3. Distributed Tracing (OpenTelemetry)

Distributed tracing implements the **W3C Trace Context specification**:
- **Ingress Tracing:** `TracingMiddleware` extracts the incoming `traceparent` header (`00-<trace_id>-<span_id>-01`). If none is present, a fresh 128-bit trace ID is generated.
- **Server Spans:** The ingress request span is created with method, route template, and status code. The active span context is propagated in the response `traceparent` header.
- **Outbound HTTP Calls:** `execute_http_request_with_retry` automatically injects the current W3C `traceparent` into outbound requests to third-party providers (e.g. mock payment gateway).
- **Attribute Redaction:** `sanitize_span_attributes()` ensures span attributes never include credentials, tokens, card details, or clinical diagnoses/prescriptions.

---

## 4. Health Probes

The service implements Kubernetes-compatible liveness and readiness probes:

### Liveness Probe (`GET /health/live`)
- **Purpose:** Verifies that the FastAPI process is responsive to event loop scheduling.
- **Dependencies:** Does not query the database or cache.
- **Response:** `200 OK` with `{"status": "ok"}`.

### Readiness Probe (`GET /health/ready`)
- **Purpose:** Validates that downstream critical dependencies are operational before receiving user traffic.
- **Checks:**
  - Executes a quick `SELECT 1` ping against PostgreSQL.
  - If Redis is configured (`RATE_LIMIT_BACKEND=redis`), executes an asynchronous `PING`.
- **Response:**
  - Healthy: `200 OK` with `{"status": "ok", "database": "connected"}` (plus `"redis": "connected"` if configured).
  - Unhealthy: `503 Service Unavailable` with `SERVICE_UNAVAILABLE` error envelope if database is unreachable.

---

## 5. Grafana Dashboard & Local Run Instructions

### Dashboard Configuration
A production-ready Grafana starter dashboard is provided at:
[`deploy/dashboards/grafana-starter.json`](file:///c:/Users/vikasln1/Classified/Amrutam-telemedicine-system/deploy/dashboards/grafana-starter.json)

**Panels included:**
1. **HTTP Request Rate by Route (RPS):** `sum(rate(http_requests_total[1m])) by (method, route)`
2. **HTTP Error Rate (4xx vs 5xx):** `sum(rate(http_requests_total{status_code=~"[45].."}[1m]))`
3. **Latency Percentiles (p50, p95, p99):** `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`
4. **Active In-Flight Requests:** `http_requests_in_flight`
5. **SQLAlchemy Connection Pool Utilization:** Gauges for `db_pool_size`, `db_pool_checked_in`, `db_pool_checked_out`
6. **Database Query Latency p95:** `histogram_quantile(0.95, sum(rate(db_query_duration_seconds_bucket[5m])) by (le, operation))`
7. **Booking Operations (Success vs 409 Conflict):** `sum(rate(booking_operations_total[1m])) by (outcome)`
8. **Transactional Outbox Lag (Seconds):** `outbox_events_lag_seconds`
9. **Background Worker Jobs & Payments:** `worker_jobs_total` and `payment_transactions_total`

### Local Scraping Verification
To test metrics locally with `curl`:
```bash
# Verify process liveness
curl http://localhost:8000/health/live

# Verify database readiness
curl http://localhost:8000/health/ready

# Scrape Prometheus metrics
curl http://localhost:8000/metrics

# Scrape with token authentication (when METRICS_AUTH_TOKEN is set)
curl -H "Authorization: Bearer <your-token>" http://localhost:8000/metrics
```

### Note on Prometheus & Grafana Containers
A full Prometheus server and Grafana instance are omitted from the default `docker-compose.yml` to conserve developer system resources (CPU and memory overhead) during local API testing. However:
- The `/metrics` endpoint is fully compliant with the standard Prometheus pull model.
- Prometheus can scrape the application directly using the target `app:8000/metrics`.
- The Grafana starter dashboard in `deploy/dashboards/grafana-starter.json` can be imported directly into any running Grafana instance.
