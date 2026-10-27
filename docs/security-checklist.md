# Security Checklist

This checklist tracks security controls required by the assignment brief. Statuses and evidence are updated only when corresponding implementation milestones and automated tests are verified.

Status definitions:
- `Not started`: Work has not yet begun.
- `Documented only`: Design and requirements are documented; architectural/infrastructure requirement.
- `Implemented`: Feature code exists and passes unit/integration tests.
- `Tested`: Thorough automated test coverage verifying security boundaries and edge cases.

| Control | Status | Evidence / notes |
|---|---|---|
| Passwords hashed with maintained algorithm (Argon2id) | Not started | Will be implemented in Milestone 07 |
| Login and MFA authentication routes are rate-limited | Not started | Will be implemented in Milestone 20 |
| Short-lived JWT access tokens with strict signature validation | Not started | Will be implemented in Milestone 08 |
| TOTP multi-factor authentication (MFA) for doctor/admin roles | Not started | Will be implemented in Milestone 08 |
| MFA secrets are encrypted at rest with environment key and never logged | Not started | Will be implemented in Milestone 08 |
| Role-based access control (RBAC) enforced server-side | Not started | Will be implemented in Milestone 08 |
| Resource ownership and doctor assignment checked on sensitive ops (no IDOR) | Not started | Will be implemented in Milestones 09–15 |
| Cross-patient data isolation (patients cannot access other patients' records) | Not started | Will be implemented in Milestones 13–15 |
| Atomic, concurrency-safe appointment booking (`SELECT FOR UPDATE` + constraints) | Not started | Will be implemented in Milestone 12 |
| Idempotency key persistence prevents duplicate writes and detects payload tampering | Not started | Will be implemented in Milestone 11 |
| Input validation with Pydantic schemas, payload limits, bounded pagination | Not started | Will be implemented in Milestones 02–10 |
| Parameterized SQL queries via SQLAlchemy ORM (SQL injection prevention) | Not started | Will be implemented in Milestone 05 |
| Sensitive data (passwords, tokens, MFA keys, PHI) redacted from logs/traces | Not started | Will be implemented in Milestones 03 and 22 |
| Environment-based configuration with secrets injected via `.env` (never hardcoded) | Not started | Will be implemented in Milestone 03 |
| `.env` excluded from version control via `.gitignore` | Not started | Will be implemented in Milestone 04 |
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
