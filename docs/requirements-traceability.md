# Requirements Traceability

This matrix maps each requirement from the assignment brief to the planned implementation, current milestone status, and the evidence to capture. All functional modules are currently marked **Not started** and will be updated as milestones are completed.

| Assignment requirement | Planned implementation | Status | Evidence to capture |
|---|---|---|---|
| User lifecycle, authentication, roles | Auth endpoints (`/api/v1/auth`), user/profile models, RBAC and resource checks | Implemented | Implemented in `app/api/v1/endpoints/auth.py`, `app/core/security.py`, `app/api/deps.py`; verified in `tests/test_auth.py` |
| Doctor availability and booking | Availability CRUD/search, row locking (`SELECT FOR UPDATE`), DB constraints, idempotency | In progress | Availability slot management and GiST exclusion constraints implemented in Milestone 10; Idempotency key persistence, canonical fingerprinting, and concurrency race handling implemented in Milestone 11; atomic consultation booking in Milestone 12 |
| Consultation lifecycle and prescriptions | Explicit state machine (`booked` → `confirmed` → `in_progress` → `completed`), prescriptions/items and access control | Not started | State-transition matrix tests and cross-user authorization tests |
| Search and filtering | Indexed doctor/list filters, bounded pagination (`page`, `page_size`), deterministic sorting (`created_at DESC, id DESC`) | Implemented | Implemented in `app/api/v1/endpoints/doctors.py` and `app/services/doctor_service.py`; verified in `tests/test_doctors.py` |
| Compliance and audit trails | Audit service, append-only structured audit events, security documentation | Not started | Audit event assertions and sensitive payload redaction verification |
| Admin analytics | Restricted aggregate endpoints (`/api/v1/admin/analytics/*`) | Not started | Admin role authorization and aggregation correctness tests |
| 100k daily consultations target | Load profile analysis, connection pooling, and scaling benchmarks | Not started | Reproducible load test script with documented assumptions and results |
| Read p95 <200 ms / write p95 <500 ms | Query tuning, indexes, load testing, measured percentiles | Not started | Measured latency output and environment details under stated profile |
| Availability 99.95% target | High-availability design, health checks, backup and DR runbooks | Not started | Architecture/DR documentation; no unverified claims of production uptime |
| Encryption, MFA, RBAC | TLS ingress, Argon2 password hashing, TOTP MFA, encrypted MFA secret, access checks | Not started | Tests for invalid/expired tokens, MFA validation, settings inspection |
| Metrics, logs, traces | Structured JSON logs, Prometheus metrics (`/metrics`), OpenTelemetry traces | Not started | Sample log output, Prometheus metric scrapes, and trace spans |
| CI/CD and containerized deployment | Docker Compose, Dockerfile, GitHub Actions workflow | Not started | Successful CI pipeline run and container build verification |
| High-level architecture / data flow | [docs/architecture.md](architecture.md) | Documented | Reviewable architecture diagram and modular monolith design document |
| Booking sequence diagram | [docs/diagrams/booking-sequence.mmd](diagrams/booking-sequence.mmd) | Documented | Validated Mermaid sequence diagram of atomic booking flow |
| ER diagram | [docs/diagrams/er-diagram.mmd](diagrams/er-diagram.mmd) | Documented | Validated Mermaid ER diagram reflecting models and foreign keys |
| API schema / contract | [docs/api-contract.md](api-contract.md) and FastAPI auto-generated OpenAPI | Documented | OpenAPI JSON schema and interactive `/docs` UI |
| Retry and backoff | Exponential backoff with jitter helper, transactional outbox worker | Not started | Unit tests for retry classifications and transient error recovery |
| Data partitioning | Range partitioning strategy in architecture doc | Documented | Clear threshold (>50M rows) and partition plan for `consultations`/`audit_logs` |
| Caching and concurrency | PostgreSQL row-locking for booking; optional cache for read models | Not started | Concurrency test suite proving zero double-booking |
| Transactions and sagas | Local atomic database transactions; saga pattern for external services | Not started | Rollback tests on mid-operation failure |
| Backup and disaster recovery | [docs/deployment-and-recovery.md](deployment-and-recovery.md), RPO/RTO goals | Documented | Documented restore procedure and integrity verification checklist |
| Security checklist and threat model | [docs/security-checklist.md](security-checklist.md), [docs/security-threat-model.md](security-threat-model.md) | Documented | Completed checklist with actual test statuses and STRIDE threat analysis |
| README and 5-minute demo | [README.md](../README.md) and final runbook | In progress | Clean setup instructions, test suite execution, and demo walk-through |

## Important distinction
The brief's targets (e.g. 100k daily consultations, p95 latency, 99.95% uptime) are requirements to be tested and designed for, not evidence of achieved production behavior in a local development environment. The submission reports measured results and limitations honestly.
