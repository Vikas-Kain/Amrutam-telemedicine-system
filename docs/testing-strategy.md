# Testing Strategy

## Core principles
- **Real persistence verification:** Concurrency, row locking (`SELECT FOR UPDATE`), foreign keys, transactions, and migration scripts must run against an active PostgreSQL database. In-memory SQLite is strictly prohibited for transaction/locking tests because it does not model PostgreSQL's concurrency semantics or constraint behaviors.
- **Privacy in testing:** Zero real patient information or production payment credentials in test fixtures.
- **Determinism:** Tests must be deterministic, isolated (cleaning up after themselves via transactional rollback or truncated test schemas), and runnable with standard commands.
- **Fail-fast CI:** Continuous integration must execute linting, format validation, unit tests, integration tests against PostgreSQL, security scans, and container builds.

## Test layers and scope

```
       / \
      /   \      Layer 6: Performance & Scalability (Locust / k6)
     /     \     Layer 5: Concurrency & Race Condition Suite
    /       \    Layer 4: Security & IDOR Authorization Tests
   /         \   Layer 3: Database & Migration Integration Tests
  /           \  Layer 2: API Route & Validation Tests (HTTPX TestClient)
 /_____________\ Layer 1: Unit Tests (Domain logic, password hashing, idempotency hashing)
```

1. **Unit tests:** Fast, pure Python tests covering password hashing/verification, TOTP logic, JWT token creation/decoding, idempotency fingerprint calculation, retry policy backoff calculations, and consultation lifecycle state transition validations.
2. **API integration tests:** Uses FastAPI `TestClient` (HTTPX) against temporary PostgreSQL test databases. Validates request headers, Pydantic validation, status codes, response envelope shapes, and pagination limits.
3. **Database integration tests:** Verifies Alembic migrations up/down, foreign key cascade constraints, unique constraints (e.g. `email_normalized`), check constraints (`consultation_fee_minor >= 0`), and transactional rollbacks.
4. **Security and authorization tests:** Explicitly attempts IDOR attacks: Patient A attempting to access Patient B's consultation, Patient calling doctor-only routes, Doctor attempting to access unassigned consultations, unauthenticated requests, and expired/tampered JWT tokens.
5. **Concurrency race condition tests:** Spawns multiple concurrent threads or async connections attempting to book the identical availability slot simultaneously. Verifies that exactly one booking succeeds (`201 Created`) while all others fail with a conflict (`409 Conflict`) without deadlocks or corrupt data.
6. **Worker and reliability tests:** Verifies transactional outbox event insertion within the business transaction, worker polling and claiming of pending events, exponential backoff retries on simulated transient failures, and dead-letter/failed-status handling after maximum retry attempts.
7. **Performance and scalability tests:** Benchmarks read endpoints (doctor listing, slot queries) and write endpoints (booking creation) under simulated load. Measures throughput, p50, p95, and p99 latency against the assignment target requirements.

## Minimum acceptance criteria
- Registration succeeds for unique email; rejects duplicate normalized emails.
- Passwords and MFA secrets are never exposed in any API response or log statement.
- Token validation rejects missing, expired, or malformed tokens.
- Doctors can only manage their own availability slots.
- Overlapping availability slots for the same doctor are rejected.
- Concurrency test proves zero double-booking under race conditions.
- Replaying a request with the same `Idempotency-Key` and payload returns the original result without re-executing writes.
- Reusing an `Idempotency-Key` with a different payload returns `409 Conflict`.
- Consultation state machine strictly rejects invalid status skips (e.g. `booked` directly to `completed`).
- Prescriptions can only be created by the doctor assigned to that specific consultation.
- Rate limiting properly returns `429 Too Many Requests` when thresholds are exceeded.
- Health endpoints (`/health/live`, `/health/ready`) and metrics (`/metrics`) function correctly.

## Tooling and execution commands

```bash
# Code style and linting
ruff check .
ruff format --check .

# Run test suite with pytest
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=term-missing --cov-fail-under=80

# Run concurrency tests only
pytest -m concurrency

# Run security tests only
pytest -m security
```
