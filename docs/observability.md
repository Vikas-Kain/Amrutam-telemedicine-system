# Observability Plan

The observability architecture provides visibility into system health, latency, business operations, and errors across the modular monolith.

## 1. Structured logging
Logs are emitted to `stdout` formatted as JSON lines in production and colored structured text in local development.

### Log schema
```json
{
  "timestamp": "2026-10-27T12:00:00.123456Z",
  "level": "INFO",
  "service": "amrutam-api",
  "environment": "production",
  "request_id": "req_01j9a4k7...",
  "correlation_id": "corr_98fbc...",
  "method": "POST",
  "path": "/api/v1/bookings",
  "route": "/api/v1/bookings",
  "status_code": 201,
  "duration_ms": 42.15,
  "user_id": "d1e4c7...",
  "action": "booking_created"
}
```

### Log sanitization rules
- Never log passwords, JWT tokens, MFA secret seeds, or authentication headers.
- Never log full HTTP request bodies for patient registration or clinical endpoints.
- Never log medical prescription contents or patient diagnostic notes.
- Use explicit allowlisted key extraction instead of dumping entire request dictionaries.

## 2. Prometheus metrics
Prometheus metrics are exposed on `/metrics` (restricted in production to internal monitoring networks).

### Core metrics inventory
- `http_requests_total`: Counter by `method`, `route_template`, and `status_code`.
- `http_request_duration_seconds`: Histogram with exponential buckets (0.005 to 10.0 seconds) for p50, p95, and p99 latency measurement.
- `http_requests_in_flight`: Gauge tracking active concurrent requests.
- `db_pool_size`, `db_pool_checked_in`, `db_pool_checked_out`: Gauges tracking SQLAlchemy connection pool utilization.
- `db_query_duration_seconds`: Histogram tracking database query execution times.
- `booking_operations_total`: Counter labeled by `outcome` (`success`, `conflict`, `error`).
- `idempotency_replays_total`: Counter tracking successful request replays vs `payload_mismatch_conflicts`.
- `outbox_events_lag_seconds`: Gauge tracking the age of the oldest unprocessed outbox event.
- `worker_jobs_total`: Counter labeled by `job_type` and `status` (`processed`, `retried`, `dead_letter`).
- `payment_transactions_total`: Counter labeled by `provider` and `status` (`pending`, `succeeded`, `failed`).

**Cardinality rule:** Labels must be strictly low-cardinality enum values (e.g. HTTP method, route template, status code). User IDs, patient emails, UUIDs, or timestamps must never be used as metric labels.

## 3. Distributed tracing (OpenTelemetry)
- FastAPI requests are automatically instrumented with W3C Trace Context propagation (`traceparent` header).
- Tracing covers:
  - Ingress HTTP span
  - Authentication and authorization verification
  - Business service operations
  - SQLAlchemy database query spans
  - Outbound HTTP provider calls
- Sensitive span attributes (user passwords, PHI, authorization bearer tokens) are explicitly scrubbed by OpenTelemetry span processors before export.

## 4. Health probes and readiness
- **Liveness probe (`GET /health/live`):** Lightweight check confirming the Python process is alive and responsive to event loops. Does not invoke database or network dependencies.
- **Readiness probe (`GET /health/ready`):** Validates that the application can serve user traffic. Executes a quick `SELECT 1` against PostgreSQL and optionally pings Redis. Returns HTTP 200 with `{"status": "ready"}` or HTTP 503 if primary storage is unreachable.

## 5. Dashboards and alerting thresholds
Recommended Grafana starter dashboard:
- **Traffic and error rate:** Requests per second (RPS) and error ratio (4xx, 5xx percentage). Alert if 5xx exceeds 1% over a 5-minute window.
- **Latency percentiles:** p50, p95, and p99 latency over time. Alert if write p95 exceeds 500ms or read p95 exceeds 200ms for >5 minutes.
- **Booking conflicts & concurrency:** Rate of 409 conflicts vs successful bookings.
- **Database health:** Connection pool checkout saturation and query latency spikes.
- **Outbox worker queue:** Unprocessed event queue depth and worker dead-letter counts.
