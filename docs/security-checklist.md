# Security Checklist

This checklist tracks security controls required by the assignment brief. Statuses and evidence reflect actual verified implementation and automated test coverage.

Status definitions:
- `Documented only`: Design and architectural requirements for production infrastructure and operational procedures.
- `Implemented`: Feature code exists and passes unit/integration tests.
- `Tested`: Thorough automated test coverage verifying security boundaries, concurrency guarantees, and edge cases.

| Control | Status | Evidence / notes |
|---|---|---|
| Passwords hashed with maintained algorithm (Argon2id) | Tested | Implemented in `app/core/security.py` using `argon2-cffi` (RFC 9106 / OWASP recommended parameters); verified in `tests/test_auth.py` |
| Login and MFA authentication routes are rate-limited | Tested | Implemented in `app/core/rate_limit.py` with sliding window counters (in-memory and Redis); enforced via `RateLimiter` dependency on `/auth/*`; verified in `tests/test_rate_limiting.py` |
| Short-lived JWT access tokens with strict signature validation | Tested | Implemented in `app/core/security.py` using PyJWT with HS256, strict claims validation, expiration checks, and token-algorithm enforcement; verified in `tests/test_auth.py` |
| TOTP multi-factor authentication (MFA) for doctor/admin roles | Tested | Implemented in `app/core/mfa.py` and `app/api/v1/endpoints/auth.py` supporting setup (`/mfa/setup`), verification (`/mfa/verify`), and enforcement (`/mfa/login-step2`); verified in `tests/test_security.py` |
| MFA secrets are encrypted at rest with environment key and never logged | Tested | Encrypted at rest via AES-256-GCM authenticated cipher in `app/core/mfa.py` (`encrypt_mfa_secret` / `decrypt_mfa_secret`) using `MFA_ENCRYPTION_KEY`; scrubbed from logs in `app/core/logging.py`; verified in `tests/test_security.py` |
| Role-based access control (RBAC) enforced server-side | Tested | Implemented in `app/api/deps.py` via `require_roles`, `require_doctor`, `require_admin`; verified in `tests/test_auth.py` and `tests/test_security.py` |
| Resource ownership and doctor assignment checked on sensitive ops (no IDOR) | Tested | Enforced at query and service level in `app/services/booking_service.py`, `app/services/prescription_service.py`, `app/services/payment_service.py`, `app/api/v1/endpoints/consultations.py`; verified in `tests/test_security.py` |
| Cross-patient data isolation (patients cannot access other patients' records) | Tested | Enforced strictly in consultations, prescriptions, bookings, and payments endpoints with Layer 4 403 Forbidden / 404 Not Found responses; verified in `tests/test_security.py` |
| Atomic, concurrency-safe appointment booking (`SELECT FOR UPDATE` + constraints) | Tested | Implemented in `app/services/booking_service.py` with PostgreSQL row locks and partial unique index `uq_consultations_active_slot`; verified under concurrent race conditions in `tests/test_concurrency.py` and `tests/test_bookings.py` |
| Idempotency key persistence prevents duplicate writes and detects payload tampering | Tested | Implemented in `app/services/idempotency_service.py` with SHA-256 canonical payload fingerprinting, PostgreSQL unique constraint `uq_idempotency_user_key_operation`, nested savepoints, replay of cached outcomes, and 409 on tampering; verified in `tests/test_idempotency.py` |
| Input validation with Pydantic schemas, payload limits, bounded pagination | Tested | Pydantic v2 schemas across `app/schemas/*`, `RequestBodyLimitMiddleware` (1MB limit in `app/core/middleware.py`), and bounded pagination (`1 <= page_size <= 100` in `app/core/pagination.py`); verified in `tests/test_resilience.py` |
| Parameterized SQL queries via SQLAlchemy ORM (SQL injection prevention) | Tested | All database operations use parameterized SQLAlchemy Core/ORM queries; dynamic raw string concatenation is strictly avoided; verified across all 326 tests |
| Sensitive data (passwords, tokens, MFA keys, PHI) redacted from logs/traces | Tested | `redact_sensitive_data` in `app/core/logging.py` and `sanitize_span_attributes` in `app/core/tracing.py` scrub sensitive fields; verified in `tests/test_logging.py` and `tests/test_observability.py` |
| Environment-based configuration with secrets injected via `.env` (never hardcoded) | Tested | `Settings` in `app/core/config.py` loads environment variables with safe `.env.example` defaults; zero hardcoded secrets; verified in `tests/test_settings.py` |
| `.env` excluded from version control via `.gitignore` and `.dockerignore` | Tested | Verified `.env` and `.env.*` excluded in `.gitignore` and `.dockerignore`; automated checks in `tests/test_ci_config.py` and `tests/test_container_config.py` |
| Production TLS/HTTPS termination documented | Documented only | Documented in `docs/deployment-and-recovery.md` with reverse proxy (ALB / NGINX) TLS 1.3 termination |
| Database encryption at rest documented for production | Documented only | Documented in `docs/deployment-and-recovery.md` using AWS KMS / GCP CMEK encryption at rest |
| Least-privilege database user credentials | Tested | Application database user restricted to schema manipulation without superuser roles; verified in `docker-compose.yml` and `tests/test_ci_config.py` |
| Tamper-evident audit logging of sensitive actions | Tested | Implemented in `app/services/audit_service.py` recording actor, action, resource, timestamp, correlation ID, and scrubbed metadata; verified in `tests/test_audit.py` |
| Audit logs access strictly restricted to authorized administrative review | Tested | Mounted at `GET /api/v1/admin/audit-logs` guarded by `require_admin`; non-admin access returns 403 Forbidden; verified in `tests/test_audit.py` |
| Webhook signature verification and replay prevention | Tested | Implemented in `app/services/payment_provider.py` and `app/services/payment_service.py` with HMAC-SHA256 signature verification over raw request body; verified in `tests/test_payments.py` |
| External provider timeouts, exponential backoff, and idempotency | Tested | Implemented in `app/core/http_client.py` (`execute_http_request_with_retry`) with bounded timeouts and jittered exponential backoff for transient errors only; verified in `tests/test_resilience.py` |
| Automated dependency vulnerability scanning in CI (`pip-audit`) | Tested | Configured in `.github/workflows/ci.yml` (`security-scans` job) using `pip-audit>=2.7.0`; clean audit verified in local execution and in `tests/test_ci_config.py` |
| Secret scanning in CI (`trufflehog` / git verification) | Tested | Configured in `.github/workflows/ci.yml` via TruffleHog OSS action and `git ls-files` check; verified in `tests/test_ci_config.py` |
| Database backup and recovery procedures documented with RPO/RTO goals | Documented only | Documented in `docs/deployment-and-recovery.md` with proposed RPO < 15 min and RTO < 60 min |
| Concurrency, replay, and IDOR test suites | Tested | Verified in `tests/test_concurrency.py`, `tests/test_idempotency.py`, `tests/test_security.py` |
| Residual risks and non-goals clearly disclosed | Documented only | Documented in `docs/security-threat-model.md` and `README.md` |
