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

## Acceptance test matrix

| Acceptance Focus | Layer | Primary Test File(s) | Key Scenarios Verified | Execution Marker / Command |
|---|---|---|---|---|
| **Registration & Redaction** | Layer 1, 2, 4 | `tests/test_auth.py`, `tests/test_security.py` | Argon2id salt uniqueness, email normalization, unique index collision, password/MFA secret exclusion from responses and logs | `pytest tests/test_auth.py` |
| **Token & MFA Lifecycle** | Layer 1, 2, 4 | `tests/test_auth.py`, `tests/test_security.py` | Valid claims (`sub`, `role`, `exp`, `iat`, `jti`), expired tokens (`TOKEN_EXPIRED`), corrupted/tampered signature (`INVALID_TOKEN`), 'none' algorithm rejection, inactive user rejection (`ACCOUNT_INACTIVE`) | `pytest -m security` |
| **Slot Ownership & Overlap** | Layer 1, 2, 4 | `tests/test_availability.py`, `tests/test_security.py` | Doctors can only manage their own slots; inverted interval rejection; batch and database overlap rejection (`409 SLOT_OVERLAP`); patient slot mutation rejection (`403`) | `pytest tests/test_availability.py` |
| **Concurrent Booking & Locking** | Layer 5 | `tests/test_concurrency.py`, `tests/test_bookings.py` | 5 parallel clients competing for identical slot in live PostgreSQL; exactly 1 succeeds (`201`), 4 fail (`409 Conflict`); zero double-booking; atomic row locking via `SELECT FOR UPDATE` | `pytest -m concurrency` |
| **Idempotency Replay & Mismatch** | Layer 1, 2, 3 | `tests/test_idempotency.py`, `tests/test_bookings.py` | Exact response body returned for identical key and payload (`is_replayed=True`); payload mismatch returns `409 Conflict`; concurrent same-key requests serialized | `pytest tests/test_idempotency.py` |
| **Cancellation & Slot Release** | Layer 2, 3, 5 | `tests/test_bookings.py`, `tests/test_concurrency.py` | Patients can cancel only their own `booked` appointments; slot atomically returned to `available`; outbox event `booking.cancelled` emitted; slot rebookable without constraint error | `pytest tests/test_bookings.py` |
| **Consultation State Machine** | Layer 1, 2, 5 | `tests/test_consultations.py`, `tests/test_concurrency.py` | Strict forward transitions (`booked` -> `confirmed` -> `in_progress` -> `completed` / `no_show`); illegal status skips rejected (`409`); concurrent transition race serialized | `pytest tests/test_consultations.py` |
| **Prescription Access & IDOR** | Layer 2, 4 | `tests/test_prescriptions.py`, `tests/test_security.py` | Only assigned doctor can issue or amend prescription; only consultation patient, assigned doctor, or admin can view; cross-patient and cross-doctor IDOR attempts blocked (`403`) | `pytest -m security` |
| **Payment Lifecycle & Webhooks** | Layer 2, 4, 5 | `tests/test_payments.py`, `tests/test_security.py`, `tests/test_concurrency.py` | Idempotent payment intent initiation; HMAC SHA256 webhook signature validation; duplicate webhook idempotent replay; cross-patient payment IDOR blocked (`403`) | `pytest tests/test_payments.py` |
| **Audit Logging & PHI Redaction** | Layer 1, 2, 4 | `tests/test_audit.py`, `tests/test_security.py` | Mandatory audit entries for booking, status transitions, prescriptions, payments; strict metadata redaction masking passwords, tokens, MFA secrets, cards, and clinical notes | `pytest tests/test_audit.py` |
| **Rate Limiting & Body Limits** | Layer 2 | `tests/test_rate_limiting.py` | Sliding window rate limits returning `429 Too Many Requests` with `Retry-After`; request body size limit enforcing 1 MB (`413 Payload Too Large`); pagination limits capped at 100 | `pytest tests/test_rate_limiting.py` |
| **Background Outbox Reliability** | Layer 3, 6 | `tests/test_outbox_worker.py` | Transactional outbox event insertion; worker claiming via `FOR UPDATE SKIP LOCKED`; exponential backoff retry on transient faults; dead-letter routing on retry exhaustion | `pytest tests/test_outbox_worker.py` |

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
