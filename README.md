# Amrutam Telemedicine Backend API

A secure, transactional, and resilient backend monolith for telemedicine consultations, built with **Python 3.12**, **FastAPI**, **PostgreSQL 16**, **SQLAlchemy 2.0 (asyncio)**, **Alembic**, and **OpenTelemetry**.

---

## Project Status

- **Milestones Completed:** All 25 architecture milestones completed and verified.
- **Automated Test Suite:** **326 passing tests** (0 failures, 0 errors, 100% test integrity across PostgreSQL transactions, locking, authorization, IDOR, idempotency, and background outbox dispatch).
- **Security Audit:** **0 known vulnerabilities** via `pip-audit`.
- **Formatting & Code Quality:** 100% compliant with `ruff format` and `ruff check`.
- **CI Pipeline:** Automated GitHub Actions pipeline validating linting, PostgreSQL integration tests, security scans, and non-root container builds.

---

## Architecture & System Invariants

1. **System of Record (PostgreSQL):** All state changes (slots, bookings, consultations, prescriptions, payments, outbox events, audit logs) reside in PostgreSQL with explicit ACID transactions.
2. **Atomic Concurrency-Safe Booking:** Slot reservation uses PostgreSQL row locks (`SELECT ... FOR UPDATE`) combined with a partial unique index `uq_consultations_active_slot (slot_id) WHERE status NOT IN ('cancelled')` to eliminate double-booking race conditions under high concurrent load.
3. **Idempotency Fingerprinting:** Sensitive mutation endpoints (`POST /api/v1/bookings`, cancellations, payments) enforce client-supplied `Idempotency-Key` headers with canonical SHA-256 payload hashing, atomic PostgreSQL persistence (`idempotency_keys`), and automatic replay without duplicate side-effects.
4. **Layer 4 Authorization & IDOR Protection:** Mandatory ownership and doctor assignment checks at the service and query layers ensure patients and doctors access strictly authorized clinical records.
5. **Transactional Outbox:** Domain events (`booking.created`, `consultation.confirmed`, `payment.succeeded`, etc.) are written transactionally alongside business data to `outbox_events` and dispatched asynchronously by a dedicated background worker (`app.worker`).
6. **Defense in Depth & Privacy:** Passwords hashed with Argon2id; TOTP MFA secrets encrypted at rest via AES-256-GCM; request bodies scrubbed of PHI and credentials before logging or tracing.

---

## Documentation Index

- [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) — Product requirements, actor roles, and assignment scope.
- [docs/architecture.md](docs/architecture.md) — Modular monolith design, concurrency, transactions, resilience, and scaling rationale.
- [docs/demo-script.md](docs/demo-script.md) — **Five-minute evaluation demo script** with step-by-step PowerShell / curl commands.
- [docs/api-contract.md](docs/api-contract.md) — REST API endpoints, query parameters, and standardized error envelopes.
- [docs/data-model.md](docs/data-model.md) — Database schema, relationships, foreign keys, and indexes.
- [docs/security-threat-model.md](docs/security-threat-model.md) — STRIDE threat catalog, mitigations, and verification evidence.
- [docs/security-checklist.md](docs/security-checklist.md) — Verification checklist of implemented and tested security controls.
- [docs/testing-strategy.md](docs/testing-strategy.md) — Unit, integration, concurrency, idempotency, and security testing layers.
- [docs/observability.md](docs/observability.md) — Structured JSON logging, Prometheus metrics catalog, and OpenTelemetry tracing.
- [docs/performance-report.md](docs/performance-report.md) — Workload mix, measured latency percentiles (p50/p95/p99), throughput, and bottleneck analysis.
- [docs/deployment-and-recovery.md](docs/deployment-and-recovery.md) — Containerization, CI pipeline, backup/restore runbook, and proposed RPO/RTO.
- [docs/diagrams/booking-sequence.mmd](docs/diagrams/booking-sequence.mmd) — Mermaid sequence diagram for idempotent atomic booking.
- [docs/diagrams/er-diagram.mmd](docs/diagrams/er-diagram.mmd) — Mermaid entity-relationship diagram for core models.
- [deploy/dashboards/grafana-starter.json](deploy/dashboards/grafana-starter.json) — Starter Grafana dashboard configuration.
- [PROGRESS.md](PROGRESS.md) — Historical chronological record of all 25 implementation milestones.

---

## Clean-Clone Setup Guide

### 1. Prerequisites
- **Python 3.12+**
- **Docker Desktop** (or local PostgreSQL 16)
- **Git**

### 2. Environment Configuration
Clone the repository and initialize the local environment configuration:

```powershell
git clone <repo-url>
cd Amrutam-telemedicine-system

# Copy template configuration
cp .env.example .env
```

Review `.env`. Default values are pre-configured for local development:
- `DATABASE_URL`: `postgresql+asyncpg://postgres:postgres@localhost:5432/amrutam_telemedicine`
- `DATABASE_TEST_URL`: `postgresql+asyncpg://postgres:postgres@localhost:5432/amrutam_telemedicine_test`
- `SECRET_KEY`: Minimum 32-character secret key for JWT signing.
- `MFA_ENCRYPTION_KEY`: Base64-encoded 32-byte key for AES-256-GCM encryption of TOTP secrets.
- `RATE_LIMIT_BACKEND`: `memory` (default) or `redis`.

### 3. Virtual Environment & Dependency Installation

```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Windows (cmd):
.\.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate

# Install dependencies in editable mode with development tools
pip install --upgrade pip
pip install -e ".[dev]"
```

---

## Running the System

### Option A: Local Processes with Containerized PostgreSQL (Recommended)

1. **Start PostgreSQL Container:**
   ```powershell
   docker compose up -d db
   ```

2. **Apply Database Migrations:**
   ```powershell
   .\.venv\Scripts\alembic.exe upgrade head
   ```

3. **Start FastAPI Application Server:**
   ```powershell
   .\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

4. **Start Background Outbox Worker (in a separate terminal):**
   ```powershell
   .\.venv\Scripts\python.exe -m app.worker
   ```

### Option B: Full Containerized Stack (Docker Compose)

Run the entire application, database, and background worker in isolated containers:

```powershell
# Build and run services in detached mode
docker compose up --build -d

# Verify container health status
docker compose ps

# Inspect logs
docker compose logs -f app
docker compose logs -f worker

# Tear down services
docker compose down
```

---

## Interactive API Documentation & OpenAPI Export

Once the server is running at `http://127.0.0.1:8000`:

- **Swagger UI (Interactive API Docs):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Raw OpenAPI JSON Specification:** [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

### Static OpenAPI JSON Export
To export the complete OpenAPI JSON schema offline without starting the server:

```powershell
.\.venv\Scripts\python.exe -c "import json, pathlib; from app.main import create_app; pathlib.Path('docs/openapi.json').write_text(json.dumps(create_app().openapi(), indent=2), encoding='utf-8')"
```

---

## Observability & Health Probes

- **Process Liveness Probe:** `GET /health/live` (HTTP 200 `{"status":"ok"}`)
- **Dependency Readiness Probe:** `GET /health/ready` (HTTP 200 `{"status":"ready","database":"connected"}`)
- **Prometheus Metrics Exposition:** `GET /metrics` or `GET /api/v1/metrics`
  - Low-cardinality route labels (`/api/v1/doctors/{id}/slots`), request latency histograms, database pool metrics, and domain counters (`booking_operations_total`, `outbox_events_lag_seconds`).
  - Supports token protection via `Authorization: Bearer <METRICS_AUTH_TOKEN>` or `X-Metrics-Key: <METRICS_AUTH_TOKEN>`.
- **Grafana Dashboard:** Import [`deploy/dashboards/grafana-starter.json`](deploy/dashboards/grafana-starter.json) into Grafana for real-time traffic, latency percentiles, error rates, and booking conflicts.

---

## Verification & Testing Commands

Execute all quality, security, and test verification commands locally:

```powershell
# 1. Format check (Ruff)
.\.venv\Scripts\ruff.exe format --check .

# 2. Lint check (Ruff)
.\.venv\Scripts\ruff.exe check .

# 3. Dependency vulnerability audit (pip-audit)
.\.venv\Scripts\pip-audit.exe

# 4. Secret & credential git hygiene check
git ls-files | Select-String -Pattern "^\.env$|^\.env\..+|.*\.pem$|.*\.key$"

# 5. Run full automated test suite (326 tests)
.\.venv\Scripts\pytest.exe -v

# 6. Run concurrency race condition tests specifically
.\.venv\Scripts\pytest.exe -m concurrency -v

# 7. Run security, MFA, and IDOR authorization tests specifically
.\.venv\Scripts\pytest.exe -m security -v

# 8. Run performance load benchmark harness
.\.venv\Scripts\python.exe tests/performance/run_benchmark.py
```

---

## Five-Minute Evaluation Demo

To evaluate the system quickly, follow the step-by-step instructions in [**docs/demo-script.md**](docs/demo-script.md).

The demo script proves:
1. **Valid Appointment Booking:** Alice books an available slot with an `Idempotency-Key` (HTTP 201).
2. **Duplicate Idempotent Retry:** Alice resends the exact request and receives the cached response without duplicate database writes (`X-Idempotent-Replay: true`).
3. **Concurrent Booking Conflict:** Bob attempts to book the same slot and is rejected with HTTP 409 Conflict (`SLOT_NOT_AVAILABLE`).
4. **Unauthorized IDOR Access Rejection:** Bob attempts to inspect Alice's consultation record and is rejected with HTTP 403 Forbidden (`FORBIDDEN`).
5. **Consultation Lifecycle Transitions:** Doctor confirms, starts, issues prescription, and completes consultation.
6. **Observability Verification:** Health checks and Prometheus operational metrics inspected.

---

## Deployment, Backup & Disaster Recovery

### Container Hardening
The production container ([`Dockerfile`](Dockerfile)) is hardened:
- **Base Image:** `python:3.12-slim-bookworm` (official, minimal Debian).
- **Multi-Stage Build:** Dependencies compiled in builder stage; build tooling excluded from runtime image.
- **Unprivileged Runtime User:** Executes as `appuser:appgroup` (UID 10001, GID 10001); root access disabled.
- **Zero Baked Credentials:** `.dockerignore` strictly excludes `.env`, secrets, git history, and caches.
- **Health Check Probe:** Configured `HEALTHCHECK` targeting `/health/live`.

### Proposed Recovery Objectives
- **Recovery Point Objective (RPO):** Proposed `< 15 minutes` via continuous PostgreSQL Write-Ahead Log (WAL) archiving to encrypted object storage.
- **Recovery Time Objective (RTO):** Proposed `< 60 minutes` via automated point-in-time restore drills and infrastructure-as-code deployment.

### Backup & Restore Runbook
See [**docs/deployment-and-recovery.md**](docs/deployment-and-recovery.md) for full backup schedules, continuous WAL archiving configuration, and disaster recovery execution procedures.

---

## Known Limitations & Design Boundaries

1. **Mock Payment Adapter:** Payment processing is simulated via `MockPaymentProviderAdapter`. It does not connect to external card acquiring networks, does not store PANs or CVVs, and makes no real monetary charges.
2. **In-Memory Rate Limiting Scope:** Default rate limiting runs in process memory (`RATE_LIMIT_BACKEND=memory`). For multi-replica container deployments, set `RATE_LIMIT_BACKEND=redis` so client quotas are shared across all instances.
3. **Slot Lock Contention:** High concurrent booking attempts targeting the same slot return HTTP 409 Conflict by design. Real-world client frontends should poll or refresh slots upon receiving conflict responses.
4. **Compliance Certification Boundary:** This codebase implements rigorous privacy and security controls (Argon2id, AES-256-GCM, audit logging, IDOR defenses), but does not constitute formal HIPAA, GDPR, or SOC-2 legal certification without third-party audit and production operational governance.
