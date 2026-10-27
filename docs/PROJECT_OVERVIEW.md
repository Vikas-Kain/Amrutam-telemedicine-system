# Project Overview — Amrutam Telemedicine Backend

## Purpose
Build a backend for a telemedicine platform that manages users and roles, doctor availability, appointment booking, consultation lifecycle, prescriptions, payment records, search/filtering, audit trails, and administrative analytics. The deliverable is a credible, testable engineering sample—not a claim that a small take-home implementation is already a fully operated healthcare production service.

## Assignment requirements
- Language: Node.js, Go, or Python; this project chooses Python.
- API: REST or GraphQL; this project chooses REST with generated OpenAPI.
- Database: PostgreSQL; Redis is optional.
- Architecture: modular services with dependency injection.
- Writes: idempotency for important write operations.
- Workloads: asynchronous jobs for heavy or deferred work.
- Security: encryption, MFA, role-based access control, input validation, rate limiting, environment-based secrets, audit trails, OWASP-oriented mitigations, and dependency scanning.
- Operations: containerized deployment, CI/CD, metrics, logs, traces, backup and disaster-recovery plan.
- Scale and targets specified by the brief: 100,000 daily consultations, p95 read latency below 200 ms, p95 write latency below 500 ms, and 99.95% availability. These are target requirements to analyze and test under documented assumptions, not facts to claim without evidence.
- Required artifacts: Git repository, README, OpenAPI/GraphQL schema, 2–4 page architecture document, tests and CI, observability setup, security checklist, threat model, and five-minute demo video.

## Technology decision
- Python with FastAPI and Pydantic.
- PostgreSQL as the source of truth.
- SQLAlchemy 2.x and Alembic for persistence and migrations.
- Password hashing with Argon2 through a maintained library; signed JWT access tokens with short expiry.
- TOTP MFA for doctor/admin accounts, with MFA secrets encrypted using a key sourced from the environment. Do not hardcode that key.
- Redis for optional shared rate limiting/cache and Celery-style background processing only when needed by the milestone plan.
- Pytest and HTTPX for tests; Ruff for linting/format checks.
- Docker and Docker Compose for repeatable local development.
- GitHub Actions for CI.
- Prometheus-compatible metrics and OpenTelemetry traces; Grafana dashboard/configuration where feasible.

Exact dependency versions should be selected, pinned, and tested by the implementation. Avoid unsupported or unmaintained dependencies.

## Architectural style
Use a modular monolith: a single deployable API with feature modules and separate API, schema, service, and repository/database layers. This is appropriate for the 4–5 day time expectation and permits a future split into services if real team, scale, and operational needs justify it. Do not pretend that folders alone make independently scalable microservices.

## Core actor roles
- `patient`: manages own profile, views doctors, books/cancels own eligible appointments, sees own consultation/prescription records.
- `doctor`: manages own availability and sees/updates consultations assigned to them; creates prescriptions only for eligible assigned consultations.
- `admin`: manages operational functions and views aggregated analytics. Access to patient clinical data should be separately authorized, limited, and audited rather than automatically granted by the role.

Roles are a starting policy. Every sensitive resource operation must also check ownership/assignment and current resource state.

## Core workflows
1. Registration/login and account lifecycle.
2. Doctor search/filtering and profile retrieval.
3. Doctors create and manage available slots.
4. Patients book a slot; atomic reservation prevents concurrent double booking and idempotency keys make safe retries possible.
5. Patient/doctor can view authorized consultations; doctor advances lifecycle through valid transitions.
6. Assigned doctor creates prescription and prescription items; patient and authorized doctor may retrieve it.
7. Payment records use a provider adapter. A mock provider is acceptable for the take-home; no real charge is made unless separately configured and explicitly required.
8. Important operations produce audit records; administrators access aggregate analytics.
9. Deferred notifications/reporting use background jobs; reliable publishing may use a transactional outbox.

## Out of scope unless the assignment evaluator asks for it
- Building a frontend or video-call/media infrastructure.
- Integrating a real payment provider or sending real email/SMS.
- Claiming a legal/compliance certification. Document relevant privacy/security considerations but do not claim HIPAA/GDPR compliance without a formal assessment.
- Operating a multi-region production platform or deploying a real managed Kubernetes cluster.

## Development workflow
Work through the prompts in `prompts/` in numeric order. For each milestone, run the prescribed checks, review the diff, manually test the relevant flow, then create a real Git commit with the commit message supplied in that prompt. Do not fabricate commit dates or commits for work not actually performed.
