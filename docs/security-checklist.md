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
| Resource ownership and doctor assignment checked on sensitive ops (no IDOR) | Not started | Will be implemented in Milestones 09–15 |
| Cross-patient data isolation (patients cannot access other patients' records) | Not started | Will be implemented in Milestones 13–15 |
| Atomic, concurrency-safe appointment booking (`SELECT FOR UPDATE` + constraints) | Not started | Will be implemented in Milestone 12 |
| Idempotency key persistence prevents duplicate writes and detects payload tampering | Implemented | Implemented in `app/services/idempotency_service.py` with canonical SHA-256 fingerprinting, PostgreSQL unique constraint `uq_idempotency_user_key_operation`, nested savepoints for race handling, replay of completed outcomes, and 409 conflict on payload mismatch or active concurrent execution; verified in `tests/test_idempotency.py` |
| Input validation with Pydantic schemas, payload limits, bounded pagination | Not started | Will be implemented in Milestones 02–10 |
| Parameterized SQL queries via SQLAlchemy ORM (SQL injection prevention) | Not started | Will be implemented in Milestone 05 |
| Sensitive data (passwords, tokens, MFA keys, PHI) redacted from logs/traces | Implemented | Implemented in `app/core/logging.py` (`redact_sensitive_data`, `StructuredJsonFormatter`); verified in `tests/test_logging.py` |
| Environment-based configuration with secrets injected via `.env` (never hardcoded) | Implemented | Implemented in `app/core/config.py` (`Settings`); template provided in `.env.example`; verified in `tests/test_settings.py` |
| `.env` excluded from version control via `.gitignore` | Implemented | Verified `.env` and `.env.*` excluded in `.gitignore` |
| Production TLS/HTTPS termination documented | Documented only | Documented in `docs/deployment-and-recovery.md` |
| Database encryption at rest documented for production | Documented only | Documented in `docs/deployment-and-recovery.md` |
| Least-privilege database user credentials | Not started | Will be implemented in Milestone 04 |
| Tamper-evident audit logging of sensitive actions | Not started | Will be implemented in Milestone 17 |
| Audit logs access strictly restricted to authorized administrative review | Not started | Will be implemented in Milestone 17 |
| Webhook signature verification and replay prevention | Not started | Will be implemented in Milestone 16 |
| External provider timeouts, exponential backoff, and idempotency | Not started | Will be implemented in Milestones 16 and 19 |
| Automated dependency vulnerability scanning in CI (`pip-audit` / `safety`) | Not started | Will be implemented in Milestone 24 |
| Secret scanning in CI (`trufflehog` / `detect-secrets`) | Not started | Will be implemented in Milestone 24 |
| Database backup and recovery procedures documented with RPO/RTO goals | Documented only | Documented in `docs/deployment-and-recovery.md` |
| Concurrency, replay, and IDOR test suites | Not started | Will be implemented in Milestone 21 |
| Residual risks and non-goals clearly disclosed | Documented only | Documented in `docs/security-threat-model.md` |
