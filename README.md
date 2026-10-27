# Amrutam Telemedicine Backend

A backend take-home project focused on secure, reliable telemedicine workflows. The repository is developed incrementally against the assignment brief. See [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) and [docs/architecture.md](docs/architecture.md) for goals, design, target requirements and trade-offs.

## Status
This README is the initial project-level entry point. Setup placeholders below will be replaced with verified commands as corresponding implementation milestones are completed. Implementation status for all functional modules is currently **Not started**.

## Planned scope
- Authentication, role-based access control (RBAC), and TOTP multi-factor authentication (MFA).
- Doctor profile search and availability management.
- Concurrency-safe, atomic, and idempotent appointment booking and cancellation.
- Consultation lifecycle state machine and prescription issuance.
- Payment records with a mock provider adapter (safe boundary without charging real cards).
- Tamper-evident audit trails and aggregate administrative analytics.
- PostgreSQL as system of record, optional Redis/background worker, Docker Compose, CI, automated tests, and observability.

## Documentation
- [AGENTS.md](AGENTS.md) — instructions and guidelines for IDE coding agents.
- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) — product goals, actor roles, and assignment scope.
- [docs/architecture.md](docs/architecture.md) — modular monolith design, concurrency, transactions, and trade-offs.
- [docs/requirements-traceability.md](docs/requirements-traceability.md) — assignment brief to planned evidence mapping.
- [docs/implementation-plan.md](docs/implementation-plan.md) — commit cadence and milestone discipline.
- [docs/api-contract.md](docs/api-contract.md) — planned REST API endpoints and schemas.
- [docs/data-model.md](docs/data-model.md) — entity relationships, constraints, and invariants.
- [docs/security-threat-model.md](docs/security-threat-model.md) — STRIDE-aligned threats, assets, and mitigations.
- [docs/security-checklist.md](docs/security-checklist.md) — controls implementation and evidence checklist.
- [docs/testing-strategy.md](docs/testing-strategy.md) — test layers, concurrency testing, and CI strategy.
- [docs/observability.md](docs/observability.md) — structured logging, Prometheus metrics, and OpenTelemetry tracing.
- [docs/deployment-and-recovery.md](docs/deployment-and-recovery.md) — containerization, backup runbooks, and disaster recovery.
- [docs/diagrams/booking-sequence.mmd](docs/diagrams/booking-sequence.mmd) — Mermaid sequence diagram for idempotent atomic booking.
- [docs/diagrams/er-diagram.mmd](docs/diagrams/er-diagram.mmd) — Mermaid entity-relationship diagram for core models.
- [amrutam_backend_agent_pack/prompts/COMMIT_PLAN.md](amrutam_backend_agent_pack/prompts/COMMIT_PLAN.md) — ordered milestones, prompts, and commit messages.

## Local setup

### Prerequisites
- Python 3.12+ (e.g. `python --version` or `py -3.12 --version`)

### 1. Virtual environment and dependency installation
Create and activate a virtual environment, then install the package in editable mode with development dependencies:

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (cmd):
.\.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 2. Run development server
Start the FastAPI application using Uvicorn:

```bash
uvicorn app.main:app --reload
```

- **Interactive API Documentation (Swagger UI):** `http://127.0.0.1:8000/docs`
- **ReDoc Documentation:** `http://127.0.0.1:8000/redoc`
- **Process Liveness Probe:** `http://127.0.0.1:8000/health/live`
- **Application Readiness Probe:** `http://127.0.0.1:8000/health/ready`
- **OpenAPI JSON Schema:** `http://127.0.0.1:8000/openapi.json`

### 3. Database persistence and migrations (Alembic)

Database schema migrations are managed via **Alembic** using asynchronous connections wired directly to application `Settings`.

```bash
# 1. Apply all pending migrations to target database
alembic upgrade head

# 2. Check current migration revision applied to target database
alembic current

# 3. View migration revision history
alembic history --verbose

# 4. Roll back the most recently applied migration
alembic downgrade -1

# 5. Generate dry-run static SQL without executing against database
alembic upgrade head --sql

# 6. Generate a new migration revision based on model changes
alembic revision --autogenerate -m "revision_description"
```

### 4. Containerized development (Docker Compose)

The repository provides a containerized development environment using Docker Compose with an unprivileged, multi-stage FastAPI application (`app`) and a PostgreSQL 16 database (`db`) with persistent storage and health monitoring.

```bash
# 1. Create local environment file from template
cp .env.example .env

# 2. Build and start containers in detached mode
docker compose up --build -d

# 3. Verify container status and health check state
docker compose ps

# 4. Inspect application logs
docker compose logs -f app

# 5. Test process liveness and readiness probes
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready

# 6. Stop containers (preserves database volume)
docker compose down

# 7. Stop containers and delete persistent database volume (wipes data)
docker compose down -v
```

### 5. Verification and testing commands

```bash
# Check code style and imports
ruff check .

# Check formatting
ruff format --check .

# Run test suite
pytest
```

## Security notice
Do not use real patient health information (PHI) or real payment credentials. This repository is an assignment implementation and must not be represented as a certified or production-operated healthcare system without formal clinical, legal, operational, and security compliance assessments.
