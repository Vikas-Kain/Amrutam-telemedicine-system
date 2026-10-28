# Security Checklist

This checklist tracks security controls required by the assignment brief. Statuses and evidence are updated only when corresponding implementation milestones and automated tests are verified.

Status definitions:
- `Not started`: Work has not yet begun.
- `Documented only`: Design and requirements are documented; architectural/infrastructure requirement.
- `Implemented`: Feature code exists and passes unit/integration tests.
- `Tested`: Thorough automated test coverage verifying security boundaries and edge cases.

| Control | Status | Evidence / notes |
|---|---|---|
| Passwords hashed with maintained algorithm (Argon2id) | Implemented | Implemented in `app/core/security.py` using `argon2-cffi` (RFC 9106 / OWASP recommended parameters); verified in `tests/test_auth.py` |
| Login and MFA authentication routes are rate-limited | Not started | Will be implemented in Milestone 20 |
| Short-lived JWT access tokens with strict signature validation | Implemented | Implemented in `app/core/security.py` using PyJWT with HS256, strict claims validation, expiration checks, and token-algorithm enforcement; verified in `tests/test_auth.py` |
| TOTP multi-factor authentication (MFA) for doctor/admin roles | Not started | Will be implemented in Milestone 20 |
| MFA secrets are encrypted at rest with environment key and never logged | Not started | Will be implemented in Milestone 20 |
| Role-based access control (RBAC) enforced server-side | Implemented | Implemented in `app/api/deps.py` via `require_roles`, `require_doctor`, `require_admin`; verified in `tests/test_auth.py` |
| Resource ownership and doctor assignment checked on sensitive ops (no IDOR) | Implemented | Enforced in `app/services/booking_service.py`, `app/services/prescription_service.py`, `app/services/payment_service.py`; verified in `tests/test_bookings.py`, `tests/test_prescriptions.py`, `tests/test_payments.py` |
| Cross-patient data isolation (patients cannot access other patients' records) | Implemented | Enforced in `app/services/booking_service.py`, `app/api/v1/endpoints/consultations.py`, `app/api/v1/endpoints/prescriptions.py`, `app/api/v1/endpoints/payments.py`; verified across test suites |
| Atomic, concurrency-safe appointment booking (`SELECT FOR UPDATE` + constraints) | Implemented | Implemented in `app/services/booking_service.py` with PostgreSQL partial unique constraints and row locking; verified in `tests/test_bookings.py` |
| Idempotency key persistence prevents duplicate writes and detects payload tampering | Implemented | Implemented in `app/services/idempotency_service.py` with canonical SHA-256 fingerprinting, PostgreSQL unique constraint `uq_idempotency_user_key_operation`, nested savepoints for race handling, replay of completed outcomes, and 409 conflict on payload mismatch or active concurrent execution; verified in `tests/test_idempotency.py` |
| Input validation with Pydantic schemas, payload limits, bounded pagination | Implemented | Implemented across `app/schemas/*` with bounded pagination (`page`, `page_size`), field limits, and strict model validations |
| Parameterized SQL queries via SQLAlchemy ORM (SQL injection prevention) | Implemented | All database access uses parameterized SQLAlchemy Core / ORM statements; verified across all services |
| Sensitive data (passwords, tokens, MFA keys, PHI) redacted from logs/traces | Implemented | Implemented in `app/core/logging.py` (`redact_sensitive_data`, `StructuredJsonFormatter`); verified in `tests/test_logging.py` |
| Environment-based configuration with secrets injected via `.env` (never hardcoded) | Implemented | Implemented in `app/core/config.py` (`Settings`); template provided in `.env.example`; verified in `tests/test_settings.py` |
| `.env` excluded from version control via `.gitignore` | Implemented | Verified `.env` and `.env.*` excluded in `.gitignore` |
| Production TLS/HTTPS termination documented | Documented only | Documented in `docs/deployment-and-recovery.md` |
| Database encryption at rest documented for production | Documented only | Documented in `docs/deployment-and-recovery.md` |
| Least-privilege database user credentials | Not started | Will be implemented in Milestone 04 |
| Tamper-evident audit logging of sensitive actions | Implemented | Implemented in `app/services/audit_service.py` with transactional atomicity for business operations, contextvar correlation ID extraction, and strict metadata sanitization/allowlisting; records critical actions across booking, consultation, availability, prescription, payment, and admin domains; verified in `tests/test_audit.py` |
| Audit logs access strictly restricted to authorized administrative review | Implemented | Exposed via `GET /api/v1/admin/audit-logs` guarded by `require_admin` dependency; supports filtering by action, resource type/ID, actor, and date ranges with bounded pagination; unauthorized/non-admin access returns 401/403; verified in `tests/test_audit.py` |
| Webhook signature verification and replay prevention | Implemented | Implemented in `app/services/payment_provider.py` and `app/services/payment_service.py` with HMAC-SHA256 signature verification and idempotent deduplication; verified in `tests/test_payments.py` |
| External provider timeouts, exponential backoff, and idempotency | Not started | Will be implemented in Milestones 16 and 19 |
| Automated dependency vulnerability scanning in CI (`pip-audit` / `safety`) | Not started | Will be implemented in Milestone 24 |
| Secret scanning in CI (`trufflehog` / `detect-secrets`) | Not started | Will be implemented in Milestone 24 |
| Database backup and recovery procedures documented with RPO/RTO goals | Documented only | Documented in `docs/deployment-and-recovery.md` |
| Concurrency, replay, and IDOR test suites | Not started | Will be implemented in Milestone 21 |
| Residual risks and non-goals clearly disclosed | Documented only | Documented in `docs/security-threat-model.md` |
