"""Prometheus metrics collector, low-cardinality registry, and text formatter.

Implements the core metrics inventory specified in docs/observability.md:
- http_requests_total, http_request_duration_seconds, http_requests_in_flight
- db_pool_size, db_pool_checked_in, db_pool_checked_out, db_query_duration_seconds
- booking_operations_total, idempotency_replays_total, outbox_events_lag_seconds
- worker_jobs_total, payment_transactions_total

Strict Low-Cardinality Rule:
Labels must only contain bounded enum-like values (method, route template, status code).
User IDs, patient emails, resource UUIDs, or timestamps must never be used as metric labels.
"""

import re
import threading
from collections.abc import Sequence
from typing import Any

# Regular expressions for scrubbing high-cardinality URL segments into templates
_UUID_REGEX = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_REGEX = re.compile(r"\b[0-9a-fA-F]{16,64}\b")
_NUMERIC_ID_REGEX = re.compile(r"/\d+(?=/|$)")


def normalize_route_template(path: str, matched_route: str | None = None) -> str:
    """Normalize raw request paths into bounded, low-cardinality route templates.

    Uses the matched FastAPI route template if it represents a full path template,
    or replaces dynamic UUID, hex, and numeric segments with '{id}' placeholders.
    """
    if matched_route and matched_route.startswith("/") and len(matched_route) > 1:
        if matched_route.count("/") >= path.count("/"):
            return matched_route
    normalized = _UUID_REGEX.sub("{id}", path)
    normalized = _HEX_REGEX.sub("{id}", normalized)
    normalized = _NUMERIC_ID_REGEX.sub("/{id}", normalized)
    return normalized or "/"


def _format_labels(labels: dict[str, str]) -> str:
    """Format label dictionary into Prometheus label syntax."""
    if not labels:
        return ""
    items = []
    for k, v in sorted(labels.items()):
        # Escape backslash, quote, and newline in label values
        escaped_val = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        items.append(f'{k}="{escaped_val}"')
    return "{" + ",".join(items) + "}"


class Counter:
    """Thread-safe monotonic Prometheus counter."""

    def __init__(self, name: str, description: str, label_names: Sequence[str] = ()):
        self.name = name
        self.description = description
        self.label_names = tuple(label_names)
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: Any) -> None:
        """Increment counter by specified positive amount."""
        if amount < 0:
            raise ValueError("Counter increments must be non-negative.")
        label_key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[label_key] = self._values.get(label_key, 0.0) + amount

    def get(self, **labels: Any) -> float:
        """Get current counter value for given label combination."""
        label_key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            return self._values.get(label_key, 0.0)

    def reset(self) -> None:
        """Reset all values to initial state."""
        with self._lock:
            self._values.clear()

    def render(self) -> list[str]:
        """Render counter to Prometheus exposition format lines."""
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            if not self._values:
                if not self.label_names:
                    lines.append(f"{self.name} 0.0")
                return lines
            for key, val in sorted(self._values.items()):
                label_dict = dict(zip(self.label_names, key, strict=False))
                lines.append(f"{self.name}{_format_labels(label_dict)} {val}")
        return lines


class Gauge:
    """Thread-safe Prometheus gauge that can arbitrarily increase and decrease."""

    def __init__(self, name: str, description: str, label_names: Sequence[str] = ()):
        self.name = name
        self.description = description
        self.label_names = tuple(label_names)
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels: Any) -> None:
        """Set gauge to exact value."""
        label_key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[label_key] = float(value)

    def inc(self, amount: float = 1.0, **labels: Any) -> None:
        """Increment gauge by amount."""
        label_key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[label_key] = self._values.get(label_key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: Any) -> None:
        """Decrement gauge by amount."""
        label_key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[label_key] = self._values.get(label_key, 0.0) - amount

    def get(self, **labels: Any) -> float:
        """Get current gauge value."""
        label_key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            return self._values.get(label_key, 0.0)

    def reset(self) -> None:
        """Reset all values to initial state."""
        with self._lock:
            self._values.clear()

    def render(self) -> list[str]:
        """Render gauge to Prometheus exposition format lines."""
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            if not self._values:
                if not self.label_names:
                    lines.append(f"{self.name} 0.0")
                return lines
            for key, val in sorted(self._values.items()):
                label_dict = dict(zip(self.label_names, key, strict=False))
                lines.append(f"{self.name}{_format_labels(label_dict)} {val}")
        return lines


class Histogram:
    """Thread-safe Prometheus histogram tracking cumulative bucket counts and sum."""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(
        self,
        name: str,
        description: str,
        label_names: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS,
    ):
        self.name = name
        self.description = description
        self.label_names = tuple(label_names)
        self.buckets = tuple(sorted(buckets))
        self._counts: dict[tuple[str, ...], int] = {}
        self._sums: dict[tuple[str, ...], float] = {}
        self._bucket_counts: dict[tuple[str, ...], dict[float, int]] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: Any) -> None:
        """Observe a measured floating-point value."""
        label_key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._counts[label_key] = self._counts.get(label_key, 0) + 1
            self._sums[label_key] = self._sums.get(label_key, 0.0) + value

            if label_key not in self._bucket_counts:
                self._bucket_counts[label_key] = dict.fromkeys(self.buckets, 0)

            for b in self.buckets:
                if value <= b:
                    self._bucket_counts[label_key][b] += 1

    def reset(self) -> None:
        """Reset all histogram buckets and counters."""
        with self._lock:
            self._counts.clear()
            self._sums.clear()
            self._bucket_counts.clear()

    def render(self) -> list[str]:
        """Render histogram to standard Prometheus exposition format."""
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            if not self._counts:
                return lines
            for key in sorted(self._counts.keys()):
                base_labels = dict(zip(self.label_names, key, strict=False))
                b_map = self._bucket_counts.get(key, {})

                # Render cumulative buckets
                for b in self.buckets:
                    b_labels = {**base_labels, "le": str(b)}
                    lines.append(f"{self.name}_bucket{_format_labels(b_labels)} {b_map.get(b, 0)}")

                # +Inf bucket equals total count
                inf_labels = {**base_labels, "le": "+Inf"}
                lines.append(
                    f"{self.name}_bucket{_format_labels(inf_labels)} {self._counts.get(key, 0)}"
                )

                # Sum and count lines
                lines.append(
                    f"{self.name}_sum{_format_labels(base_labels)} {self._sums.get(key, 0.0)}"
                )
                lines.append(
                    f"{self.name}_count{_format_labels(base_labels)} {self._counts.get(key, 0)}"
                )
        return lines


class MetricsRegistry:
    """Central registry holding all operational and domain metric instruments."""

    def __init__(self) -> None:
        self._metrics: dict[str, Counter | Gauge | Histogram] = {}
        self._lock = threading.Lock()

    def register(self, metric: Counter | Gauge | Histogram) -> None:
        """Register a metric instrument."""
        with self._lock:
            self._metrics[metric.name] = metric

    def reset_all(self) -> None:
        """Reset all registered metrics (useful in test suites)."""
        with self._lock:
            for m in self._metrics.values():
                m.reset()

    def collect(self) -> str:
        """Sample dynamic resources and render all metrics in Prometheus text format."""
        self._sample_database_pool()
        rendered_sections = []
        with self._lock:
            for metric in self._metrics.values():
                lines = metric.render()
                if lines:
                    rendered_sections.append("\n".join(lines))
        return "\n\n".join(rendered_sections) + "\n"

    def _sample_database_pool(self) -> None:
        """Sample SQLAlchemy connection pool sizes dynamically from active engine."""
        try:
            from app.db.session import _engine

            if _engine is not None and hasattr(_engine.sync_engine, "pool"):
                pool = _engine.sync_engine.pool
                size_fn = getattr(pool, "size", None)
                checkedin_fn = getattr(pool, "checkedin", None)
                checkedout_fn = getattr(pool, "checkedout", None)

                if callable(size_fn):
                    db_pool_size.set(float(size_fn()))
                if callable(checkedin_fn):
                    db_pool_checked_in.set(float(checkedin_fn()))
                if callable(checkedout_fn):
                    db_pool_checked_out.set(float(checkedout_fn()))
        except Exception:
            # Metrics sampling must never disrupt request execution
            pass


# Global singleton registry
registry = MetricsRegistry()

# ---------------------------------------------------------------------------
# Pre-Registered Core Observability Metrics
# ---------------------------------------------------------------------------

# HTTP Request Metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed by method, route template, and status code",
    label_names=["method", "route", "status_code"],
)
registry.register(http_requests_total)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds measured across low-cardinality route templates",
    label_names=["method", "route"],
)
registry.register(http_request_duration_seconds)

http_requests_in_flight = Gauge(
    "http_requests_in_flight",
    "Number of HTTP requests currently executing inside application middleware",
)
registry.register(http_requests_in_flight)

# Database Connection Pool Metrics
db_pool_size = Gauge(
    "db_pool_size",
    "Current configured SQLAlchemy connection pool capacity",
)
registry.register(db_pool_size)

db_pool_checked_in = Gauge(
    "db_pool_checked_in",
    "Number of idle database connections currently available in SQLAlchemy connection pool",
)
registry.register(db_pool_checked_in)

db_pool_checked_out = Gauge(
    "db_pool_checked_out",
    "Number of active database connections currently checked out by active transactions",
)
registry.register(db_pool_checked_out)

db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "Execution duration of database operations in seconds",
    label_names=["operation"],
)
registry.register(db_query_duration_seconds)

# Domain & Business Operation Metrics
booking_operations_total = Counter(
    "booking_operations_total",
    "Total appointment booking workflow outcomes (success, conflict, error)",
    label_names=["outcome"],
)
registry.register(booking_operations_total)

idempotency_replays_total = Counter(
    "idempotency_replays_total",
    "Total idempotency key claim and replay outcomes (replayed, payload_mismatch)",
    label_names=["outcome"],
)
registry.register(idempotency_replays_total)

outbox_events_lag_seconds = Gauge(
    "outbox_events_lag_seconds",
    "Age in seconds of the oldest pending transactional outbox event awaiting dispatch",
)
registry.register(outbox_events_lag_seconds)

worker_jobs_total = Counter(
    "worker_jobs_total",
    "Total transactional outbox worker event execution attempts by job type and status",
    label_names=["job_type", "status"],
)
registry.register(worker_jobs_total)

payment_transactions_total = Counter(
    "payment_transactions_total",
    "Total payment transaction outcomes by provider and status",
    label_names=["provider", "status"],
)
registry.register(payment_transactions_total)


# ---------------------------------------------------------------------------
# Public Convenience Recorders
# ---------------------------------------------------------------------------


def record_booking_metric(outcome: str) -> None:
    """Record appointment booking operation outcome ('success', 'conflict', 'error')."""
    booking_operations_total.inc(outcome=outcome)


def record_idempotency_metric(outcome: str) -> None:
    """Record idempotency outcome ('replayed', 'payload_mismatch')."""
    idempotency_replays_total.inc(outcome=outcome)


def record_payment_metric(provider: str, status: str) -> None:
    """Record payment lifecycle outcome by provider and status ('succeeded', 'failed', etc.)."""
    payment_transactions_total.inc(provider=provider, status=status)


def record_worker_metric(job_type: str, status: str) -> None:
    """Record worker event execution ('processed', 'retried', 'dead_letter')."""
    worker_jobs_total.inc(job_type=job_type, status=status)


def record_outbox_lag_metric(lag_seconds: float) -> None:
    """Record lag of oldest pending outbox event."""
    outbox_events_lag_seconds.set(max(0.0, lag_seconds))


def generate_prometheus_metrics() -> str:
    """Serialize all registered metrics to Prometheus text exposition format."""
    return registry.collect()


def reset_metrics() -> None:
    """Reset all metric values for deterministic testing."""
    registry.reset_all()
