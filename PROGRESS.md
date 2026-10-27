# Project Implementation Progress & Verification Guide

This document tracks the incremental implementation of the **Amrutam Telemedicine Backend** against the assignment requirements and the 25-milestone roadmap. It explains what has been built, the architectural rationale, and step-by-step verification procedures for each milestone.

---

## Overall Roadmap Status

| Milestone | Description | Commit Message | Status |
|:---:|---|---|:---:|
| **01** | Architecture & Project Implementation Plan | `docs: add architecture and project implementation plan` | **Completed & Committed** |
| **02** | Bootstrap FastAPI Package & Developer Tooling | `chore: bootstrap FastAPI application and developer tooling` | **Completed & Committed** |
| **03** | Settings, Structured Logging & API Error Handling | `feat: add application settings and structured error handling` | **Completed & Committed** |
| **04** | Local PostgreSQL & Docker Development | `build: add Docker Compose development environment` | **Completed & Committed** |
| **05** | SQLAlchemy Persistence & Alembic Migrations | `feat: add PostgreSQL persistence and Alembic migrations` | **Completed & Committed** |
| **06** | Core Database Models | `feat: add core telemedicine database models` | **Implemented (Pending Commit)** |
| **07** | User Registration & Argon2 Password Hashing | `feat: add user registration and secure password hashing` | **Implemented (Pending Commit)** |
| **08** | JWT Authentication & Role-Based Authorization | `feat: add JWT authentication and role-based authorization` | *Next Up* |
| **09** | Doctor Profiles & Searchable Listing | `feat: add doctor profiles and search filters` | *Planned* |
| **10** | Doctor Availability Slot Management | `feat: add doctor availability management` | *Planned* |
| **11** | Idempotency Storage & Request Handling | `feat: add idempotency key persistence for write requests` | *Planned* |
| **12** | Atomic, Concurrency-Safe Booking Workflow | `feat: implement atomic idempotent appointment booking` | *Planned* |
| **13** | Booking Retrieval & Cancellation Lifecycle | `feat: add booking retrieval and cancellation lifecycle` | *Planned* |
| **14** | Consultation Lifecycle State Machine | `feat: enforce consultation lifecycle transitions` | *Planned* |
| **15** | Prescriptions & Item Authorization | `feat: add prescription and prescription-item workflows` | *Planned* |
| **16** | Payment Lifecycle & Mock Provider Adapter | `feat: add payment lifecycle with mock provider adapter` | *Planned* |
| **17** | Audit Logging for Sensitive Operations | `feat: add audit logging for sensitive operations` | *Planned* |
| **18** | Aggregate Admin Analytics | `feat: add aggregate admin analytics` | *Planned* |
| **19** | Background Jobs & Transactional Outbox | `feat: add background jobs and transactional outbox` | *Planned* |
| **20** | Rate Limiting & Resilience Policies | `feat: add rate limiting and resilience policies` | *Planned* |
| **21** | Core API & Security Test Coverage | `test: complete core API and security test coverage` | *Planned* |
| **22** | Logs, Metrics, Traces & Health Probes | `feat: instrument logs, metrics, traces, and health checks` | *Planned* |
| **23** | Performance Benchmark & Scaling Scenarios | `test: add performance test scenarios and scaling evidence` | *Planned* |
| **24** | Container Build & CI Security Hardening | `build: harden container build and CI security checks` | *Planned* |
| **25** | Final Documentation & Demo Runbook | `docs: finalize documentation and demo runbook` | *Planned* |

---

## Detailed Milestone Documentation

### Milestone 01: Architecture & Project Guidance
- **Commit:** `b2c754b docs: add architecture and project implementation plan`
- **Scope:** Establish the complete documentation baseline, system architecture, data models, and verification plans before writing code.

#### What Was Implemented:
1. **System Architecture ([docs/architecture.md](docs/architecture.md)):**
   - Defined modular monolith architecture utilizing Python, FastAPI, and PostgreSQL.
   - Designed atomic booking mechanics using row-level locks (`SELECT ... FOR UPDATE`), partial unique constraints (`UNIQUE (slot_id) WHERE status NOT IN ('cancelled')`), and idempotency keys to eliminate double-booking.
   - Designed range partitioning strategy for high-volume tables (`consultations`, `audit_logs`) with a documented threshold (>50M rows / >50 GB).
   - Documented asynchronous transactional outbox pattern to decouple event dispatch from the local database transaction.
2. **Data Model Specifications ([docs/data-model.md](docs/data-model.md)):**
   - Fully detailed logical schema for 11 core tables (`users`, `profiles`, `doctors`, `availability_slots`, `consultations`, `prescriptions`, `prescription_items`, `payments`, `audit_logs`, `idempotency_keys`, `outbox_events`).
   - Stored currency in integer minor units (paise/cents) to prevent floating-point inaccuracies.
3. **API Contract ([docs/api-contract.md](docs/api-contract.md)):**
   - Outlined REST endpoints under `/api/v1` for Auth, Doctors, Bookings, Prescriptions, Payments, Admin Analytics, and Health/Metrics.
4. **Security & Governance ([docs/security-threat-model.md](docs/security-threat-model.md) & [docs/security-checklist.md](docs/security-checklist.md)):**
   - Established STRIDE threat model covering IDOR, credential stuffing, booking races, replay attacks, and sensitive data leakage.
   - Security checklist tracking status of 27 security controls, initialized to `Not started`.
5. **Testing & Observability Plans ([docs/testing-strategy.md](docs/testing-strategy.md) & [docs/observability.md](docs/observability.md)):**
   - Defined 7 testing layers; enforced PostgreSQL for concurrency/locking tests (banning in-memory SQLite for transaction testing).
   - Documented structured JSON logging format, low-cardinality Prometheus metrics, and OpenTelemetry trace spans.
6. **Visual Diagrams ([docs/diagrams/](docs/diagrams/)):**
   - `booking-sequence.mmd`: Autonumbered Mermaid sequence diagram showing the atomic booking lifecycle, replay path, conflict rollback, and worker outbox dispatch.
   - `er-diagram.mmd`: Complete Mermaid ER diagram showing entity relationships and attribute types.

#### How to Verify Milestone 01:
Run these commands from your terminal:
```powershell
# 1. Verify git commit exists
git log -1 --oneline

# 2. Verify all documentation files are present
Get-ChildItem -Path docs -Recurse -File | Select-Object Name, Length
```

---

### Milestone 02: Bootstrap FastAPI Package & Developer Tooling
- **Branch/Status:** Working directory (Ready to commit)
- **Scope:** Set up the smallest runnable FastAPI application, modern Python package configuration, linting, formatting, and automated tests.

#### What Was Implemented:
1. **Project Configuration ([pyproject.toml](pyproject.toml)):**
   - Configured modern Python packaging using **Hatchling** (`build-backend = "hatchling.build"`).
   - Targeted Python `>=3.12`.
   - Pinned production dependencies: `fastapi`, `pydantic`, `pydantic-settings`, `uvicorn[standard]`.
   - Configured developer dependencies: `pytest`, `pytest-asyncio`, `httpx`, `ruff`.
   - Set up **Ruff** rules (`E`, `W`, `F`, `I`, `B`, `C4`, `UP`) with a line length of 100 characters.
   - Set up **Pytest** with `asyncio_mode = "auto"`.
2. **Application Layout ([app/](app/)):**
   - Created clean package initializers: `app/__init__.py`, `app/api/__init__.py`, `app/api/v1/__init__.py`, and `app/api/v1/endpoints/__init__.py`.
   - Created [app/main.py](app/main.py) implementing the application factory pattern (`create_app() -> FastAPI`). Kept feature logic completely out of `main.py`.
   - Created [app/api/v1/router.py](app/api/v1/router.py) as the versioned API router skeleton mounted under `/api/v1`.
   - Created [app/api/v1/endpoints/health.py](app/api/v1/endpoints/health.py) defining:
     - `LivenessResponse` Pydantic model (`{"status": "ok"}`).
     - `GET /health/live` endpoint returning HTTP 200 without external dependencies.
3. **Automated Test Suite ([tests/](tests/)):**
   - Created [tests/conftest.py](tests/conftest.py) providing an isolated FastAPI `TestClient` fixture.
   - Created [tests/test_health.py](tests/test_health.py) with 3 automated tests:
     - `test_health_live_endpoint`: Verifies `GET /health/live` returns HTTP 200 and `{"status": "ok"}`.
     - `test_api_v1_health_live_endpoint`: Verifies versioned `GET /api/v1/health/live` responds.
     - `test_openapi_schema_generated`: Verifies OpenAPI schema generation and doc accessibility.
4. **Environment Isolation & Documentation:**
   - Updated [.gitignore](.gitignore) to exclude `.venv/`, `__pycache__/`, `.pytest_cache/`, and `.ruff_cache/`.
   - Updated [README.md](README.md) with verified commands for venv activation, server startup, and test execution.

---

## Step-by-Step Verification Guide for Milestone 02

Follow these instructions to verify every part of Milestone 02 locally:

### Step 1: Activate Virtual Environment
Open PowerShell in the project directory:
```powershell
# Activate local virtual environment
.\.venv\Scripts\Activate.ps1
```
*(Your command prompt will display `(.venv)` when active).*

> **Tip:** If PowerShell displays an execution policy error, enable local scripts once by running:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

---

### Step 2: Verify Linting (Ruff Check)
Run the Ruff linter to confirm code quality and clean imports:
```powershell
ruff check .
```
**Expected Output:**
```
All checks passed!
```

---

### Step 3: Verify Code Formatting (Ruff Format)
Run Ruff format check to ensure all files match project formatting rules:
```powershell
ruff format --check .
```
**Expected Output:**
```
22 files already formatted
```

---

### Step 4: Run Automated Tests (Pytest)
Run the test suite with verbose output:
```powershell
pytest -v
```
**Expected Output:**
```
tests/test_health.py::test_health_live_endpoint PASSED           [ 33%]
tests/test_health.py::test_api_v1_health_live_endpoint PASSED    [ 66%]
tests/test_health.py::test_openapi_schema_generated PASSED       [100%]
============================== 3 passed in 0.05s ==============================
```

---

### Step 5: Start the Development Server & Test Live Endpoints
Start the local server with hot-reload enabled:
```powershell
uvicorn app.main:app --reload
```
**Expected Server Log:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

While the server is running, test the endpoints in a second terminal or browser:

1. **Liveness Probe:**
   - **URL:** `http://127.0.0.1:8000/health/live`
   - **Command:** `curl.exe http://127.0.0.1:8000/health/live`
   - **Response:** `{"status":"ok"}` (HTTP 200)

2. **Interactive Swagger Documentation:**
   - Open in browser: `http://127.0.0.1:8000/docs`
   - Confirms interactive OpenAPI documentation is rendered.

3. **ReDoc Documentation:**
   - Open in browser: `http://127.0.0.1:8000/redoc`

4. **Raw OpenAPI JSON Specification:**
   - **URL:** `http://127.0.0.1:8000/openapi.json`
   - **Command:** `curl.exe http://127.0.0.1:8000/openapi.json`

---

### Step 6: Create the Milestone 02 Git Commit
Once verified, stage and commit Milestone 02:
```bash
git add pyproject.toml app/ tests/ .gitignore README.md PROGRESS.md
git commit -m "chore: bootstrap FastAPI application and developer tooling"
```

---

### Milestone 03: Settings, Structured Logging & API Errors
- **Commit Message:** `feat: add application settings and structured error handling`
- **Scope:** Implement typed Pydantic Settings, secure structured logging with sensitive data redaction, request/correlation ID tracking middleware, standardized error envelopes, and sanitized global exception handlers.

#### What Was Implemented:
1. **Central Typed Settings ([app/core/config.py](app/core/config.py)):**
   - Implemented `Settings(BaseSettings)` powered by `pydantic-settings`.
   - Manages configuration for application identity, security keys (`SECRET_KEY`, `MFA_ENCRYPTION_KEY`), database connection strings, pool sizing, Redis, and log configuration.
   - Built-in validation: Enforces allowed environments (`development`, `staging`, `production`, `test`), allowed log levels, and minimum 16-character secret key length.
   - Cached singleton getter: `@lru_cache def get_settings() -> Settings`.
2. **Environment Variables Template & Git Exclusion:**
   - Created [.env.example](.env.example) documenting all available environment variables with safe development defaults and security warnings.
   - Updated [.gitignore](.gitignore) to ensure `.env`, `.env.*`, and local database files (`*.db`, `*.sqlite`, `*.sqlite3`) are strictly excluded from source control.
3. **Safe Structured Logging ([app/core/logging.py](app/core/logging.py)):**
   - Implemented `StructuredJsonFormatter` emitting JSON with UTC ISO timestamp, log level, service name, environment, logger name, `request_id`, and `correlation_id`.
   - Implemented `ConsoleFormatter` for readable local development console output.
   - Implemented `redact_sensitive_data()`: Recursively scrubs sensitive keys (`password`, `token`, `secret`, `authorization`, `cookie`, `card`, `cvv`, `prescription`, `diagnosis`) to prevent credential or PHI leakage into logs.
4. **Request & Correlation ID Middleware ([app/core/middleware.py](app/core/middleware.py)):**
   - Extracts or generates `X-Request-ID` (`req_<uuid4>`) and `X-Correlation-ID`.
   - Propagates identifiers into async `contextvars` (`request_id_ctx_var`, `correlation_id_ctx_var`) for transparent inclusion in log records without global mutable state.
   - Injects identifiers into outgoing response headers.
   - Logs request duration (in milliseconds) and status code safely.
   - Guarantees context variable cleanup in `finally` block to prevent cross-request pollution.
5. **Standardized Error Handling & Sanitization ([app/core/errors.py](app/core/errors.py) & [app/core/handlers.py](app/core/handlers.py)):**
   - Implemented `AppException` hierarchy: `BadRequestError` (400), `UnauthorizedError` (401), `ForbiddenError` (403), `NotFoundError` (404), `ConflictError` (409), `ValidationException` (422), `ServiceUnavailableError` (503).
   - Standardized `ErrorResponse` envelope matching `docs/api-contract.md`:
     ```json
     {
       "error": {
         "code": "ERROR_CODE",
         "message": "Human readable message",
         "request_id": "req_..."
       }
     }
     ```
   - Global exception handlers:
     - `AppException`: Returns appropriate status code and formatted error payload.
     - `RequestValidationError`: Formats Pydantic validation errors cleanly without raw bodies.
     - `StarletteHTTPException`: Maps status codes to standard error codes.
     - Unhandled `Exception`: Logs full stack trace internally with correlation ID, but returns a generic HTTP 500 error to the client with **zero stack traces, SQL syntax, or internal file paths**.
6. **Automated Test Suite (19 tests):**
   - [tests/test_settings.py](tests/test_settings.py): Tests default settings, environment overrides, and rejection of invalid environments/log levels/secret keys.
   - [tests/test_middleware.py](tests/test_middleware.py): Tests request ID generation, header propagation, correlation ID preservation, and contextvar isolation.
   - [tests/test_errors.py](tests/test_errors.py): Tests custom error responses (404, 409), validation errors (422), and confirms 500 crashes never leak internal details.
   - [tests/test_logging.py](tests/test_logging.py): Tests sensitive field redaction and JSON log formatting.
   - [tests/test_health.py](tests/test_health.py): Health probe verification.

---

## Step-by-Step Verification Guide for Milestone 03

Follow these instructions to verify every part of Milestone 03:

### Step 1: Run Ruff Linter
Verify that all core modules, middleware, and tests adhere to code quality rules:
```powershell
ruff check .
```
**Expected Output:**
```
All checks passed!
```

---

### Step 2: Run Ruff Format Check
Verify consistent formatting across the codebase:
```powershell
ruff format --check .
```
**Expected Output:**
```
33 files already formatted
```

---

### Step 3: Run the Complete Test Suite
Execute Pytest to run all 19 unit and API integration tests:
```powershell
pytest -v
```
**Expected Output:**
```
tests/test_errors.py::test_not_found_error_response_shape PASSED         [  5%]
tests/test_errors.py::test_conflict_error_response_with_details PASSED   [ 10%]
tests/test_errors.py::test_validation_error_response_shape PASSED       [ 15%]
tests/test_errors.py::test_unhandled_exception_sanitization PASSED       [ 21%]
tests/test_health.py::test_health_live_endpoint PASSED                  [ 26%]
tests/test_health.py::test_api_v1_health_live_endpoint PASSED           [ 31%]
tests/test_health.py::test_openapi_schema_generated PASSED              [ 36%]
tests/test_logging.py::test_redact_sensitive_data_masks_passwords_and_tokens PASSED [ 42%]
tests/test_logging.py::test_structured_json_formatter_output PASSED     [ 47%]
tests/test_middleware.py::test_generated_request_id_in_response PASSED  [ 52%]
tests/test_middleware.py::test_inbound_request_id_preserved PASSED      [ 57%]
tests/test_middleware.py::test_inbound_correlation_id_preserved PASSED  [ 63%]
tests/test_middleware.py::test_context_variables_cleared_after_request PASSED [ 68%]
tests/test_settings.py::test_default_settings_instantiation PASSED      [ 73%]
tests/test_settings.py::test_get_settings_cached_singleton PASSED       [ 78%]
tests/test_settings.py::test_settings_environment_override PASSED       [ 84%]
tests/test_settings.py::test_invalid_app_env_raises_validation_error PASSED [ 89%]
tests/test_settings.py::test_invalid_log_level_raises_validation_error PASSED [ 94%]
tests/test_settings.py::test_short_secret_key_raises_validation_error PASSED [100%]
============================= 19 passed in 0.19s =============================
```

---

### Step 4: Verify Request ID Propagation & Header Inspection
Start the development server:
```powershell
uvicorn app.main:app --reload
```
In a separate terminal, test request ID generation and custom propagation:
```powershell
# Case A: Auto-generated Request ID
curl.exe -i http://127.0.0.1:8000/health/live

# Case B: Inbound Custom Request ID
curl.exe -i -H "X-Request-ID: my-custom-id-999" http://127.0.0.1:8000/health/live
```
**Verify:** The response headers contain:
```http
X-Request-ID: my-custom-id-999
X-Correlation-ID: my-custom-id-999
```

---

### Step 5: Verify Standardized 404 Error Envelope
Send a request to a non-existent route:
```powershell
curl.exe -i http://127.0.0.1:8000/non-existent-route
```
**Expected Response:**
```json
HTTP/1.1 404 Not Found
content-type: application/json
x-request-id: req_...

{
  "error": {
    "code": "NOT_FOUND",
    "message": "Not Found",
    "request_id": "req_..."
  }
}
```

---

### Step 6: Create the Milestone 03 Git Commit
Stage and commit Milestone 03:
```bash
git add app/ tests/ .env.example .gitignore docs/security-checklist.md PROGRESS.md
git commit -m "feat: add application settings and structured error handling"
```

---

### Milestone 04: Local PostgreSQL & Docker Development
- **Commit Message:** `build: add Docker Compose development environment`
- **Scope:** Build multi-stage Dockerfile targeting Python 3.12-slim, non-root user execution, Docker Compose environment with PostgreSQL 16 Alpine and FastAPI `app`, health check probes (`pg_isready` and `/health/live`), persistent volume (`pgdata`), secret exclusion via `.dockerignore`, deferred Redis, explicit avoidance of automatic worker migrations, and documented limitations.

#### What Was Implemented:
1. **Multi-Stage Dockerfile ([Dockerfile](Dockerfile)):**
   - **Builder stage:** Uses `python:3.12-slim-bookworm` to create isolated `/opt/venv`, installs production dependencies from `pyproject.toml` without retaining build caches (`PIP_NO_CACHE_DIR=1`).
   - **Runtime stage:** Uses minimal `python:3.12-slim-bookworm`, installs `curl` for container health monitoring, and creates unprivileged system group `appgroup` (GID 10001) and user `appuser` (UID 10001).
   - **Non-root execution:** Switches to `USER appuser` prior to execution.
   - **Clean signal handling:** Launches Uvicorn as PID 1 via exec form (`CMD ["uvicorn", "app.main:app", ...]`) for clean `SIGTERM` connection draining.
   - **Healthcheck probe:** Built-in `HEALTHCHECK` running every 30 seconds against `/health/live`.
   - **No baked secrets:** Strict enforcement that `.env` files or credentials are never copied into the container image.
2. **Container Build Ignore Rules ([.dockerignore](.dockerignore)):**
   - Strictly excludes `.git`, `.venv`, `.env`, `.env.*` (while retaining `!.env.example`), local databases (`*.db`, `*.sqlite`), bytecode, test caches, docs, and test suites from Docker build context.
3. **Local Docker Compose Environment ([docker-compose.yml](docker-compose.yml)):**
   - **`db` service:** Runs `postgres:16-alpine`, mounts persistent volume `pgdata:/var/lib/postgresql/data`, exposes port 5432, and implements health probe `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`.
   - **`app` service:** Builds from local `Dockerfile`, mounts `./app:/app/app:ro` for live code reload in development, and maps port 8000.
   - **Startup synchronization:** Configures `depends_on: db: condition: service_healthy` ensuring the API worker does not start until PostgreSQL passes its readiness check.
   - **No unsafe auto-migrations:** Does not run automatic database migrations on container startup; migrations are kept as explicit administrative operations.
   - **Redis deferral:** Deferred Redis service container until caching or background worker milestones actually require it, keeping local resource usage minimal.
4. **Environment Variables Template ([.env.example](.env.example)):**
   - Documented Docker Compose PostgreSQL parameters (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`).
5. **Automated Configuration Tests ([tests/test_container_config.py](tests/test_container_config.py)):**
   - `test_dockerfile_exists_and_configured`: Validates Python 3.12 slim base, non-root user `appuser`, health check, and absence of secret copies.
   - `test_dockerignore_configuration`: Validates exclusion of `.env`, `.venv`, and cache directories.
   - `test_docker_compose_services_and_healthchecks`: Validates `db` and `app` definitions, PostgreSQL 16 image, `pg_isready` probe, `service_healthy` startup dependency, persistent volume `pgdata`, absence of unsafe migration scripts, and Redis deferral.
6. **Milestone Limitation Transparency:**
   - Clearly documented in [README.md](README.md) and [PROGRESS.md](PROGRESS.md) that while containerized PostgreSQL 16 and health waiting are established in Milestone 04, database persistence (SQLAlchemy engine/session lifecycle) and schema migrations (Alembic) are scheduled for Milestone 05. The API currently serves stateless endpoints (`/health/live`, `/docs`).

---

## Step-by-Step Verification Guide for Milestone 04

Follow these instructions to verify every part of Milestone 04 locally:

### Step 1: Run Ruff Linter
Verify that all test files and source code adhere to formatting and import standards:
```powershell
.\.venv\Scripts\ruff check .
```
**Expected Output:**
```
All checks passed!
```

---

### Step 2: Run Ruff Format Check
Verify consistent formatting across all 34 repository files:
```powershell
.\.venv\Scripts\ruff format --check .
```
**Expected Output:**
```
34 files already formatted
```

---

### Step 3: Run the Complete Test Suite
Execute Pytest to run all 22 unit, API integration, and container configuration tests:
```powershell
.\.venv\Scripts\pytest -v
```
**Expected Output:**
```
tests/test_container_config.py::test_dockerfile_exists_and_configured PASSED    [  4%]
tests/test_container_config.py::test_dockerignore_configuration PASSED          [  9%]
tests/test_container_config.py::test_docker_compose_services_and_healthchecks PASSED [ 13%]
tests/test_errors.py::test_not_found_error_response_shape PASSED                [ 18%]
tests/test_errors.py::test_conflict_error_response_with_details PASSED          [ 22%]
tests/test_errors.py::test_validation_error_response_shape PASSED              [ 27%]
tests/test_errors.py::test_unhandled_exception_sanitization PASSED              [ 31%]
tests/test_health.py::test_health_live_endpoint PASSED                         [ 36%]
tests/test_health.py::test_api_v1_health_live_endpoint PASSED                  [ 40%]
tests/test_health.py::test_openapi_schema_generated PASSED                     [ 45%]
tests/test_logging.py::test_redact_sensitive_data_masks_passwords_and_tokens PASSED [ 50%]
tests/test_logging.py::test_structured_json_formatter_output PASSED            [ 54%]
tests/test_middleware.py::test_generated_request_id_in_response PASSED         [ 59%]
tests/test_middleware.py::test_inbound_request_id_preserved PASSED             [ 63%]
tests/test_middleware.py::test_inbound_correlation_id_preserved PASSED         [ 68%]
tests/test_middleware.py::test_context_variables_cleared_after_request PASSED [ 72%]
tests/test_settings.py::test_default_settings_instantiation PASSED             [ 77%]
tests/test_settings.py::test_get_settings_cached_singleton PASSED              [ 81%]
tests/test_settings.py::test_settings_environment_override PASSED              [ 86%]
tests/test_settings.py::test_invalid_app_env_raises_validation_error PASSED    [ 90%]
tests/test_settings.py::test_invalid_log_level_raises_validation_error PASSED [ 95%]
tests/test_settings.py::test_short_secret_key_raises_validation_error PASSED   [100%]
============================= 22 passed in 0.30s ==============================
```

---

### Step 4: Docker Compose Runtime Verification (where Docker Engine is present)
In an environment with Docker Engine / Docker Desktop installed:
```powershell
# 1. Build and start services in background
docker compose up --build -d

# 2. Check service status (both should report healthy)
docker compose ps

# 3. Test API liveness endpoint
curl.exe http://localhost:8000/health/live

# 4. Tear down containers (preserving database volume)
docker compose down
```

---

### Step 5: Create the Milestone 04 Git Commit
Once verified, stage and commit Milestone 04:
```bash
git add Dockerfile .dockerignore docker-compose.yml .env.example README.md PROGRESS.md tests/test_container_config.py
git commit -m "build: add Docker Compose development environment"
```

---

### Milestone 05: SQLAlchemy Database Layer & Alembic Migrations
- **Commit Message:** `feat: add PostgreSQL persistence and Alembic migrations`
- **Scope:** Configure SQLAlchemy 2.x async engine, session factory, and dependency-injected session lifecycle (`get_db_session`). Set up Alembic migration environment wired to application `Settings`. Provide an application readiness probe (`/health/ready`) that verifies database connectivity without leaking credentials. Implement an initial schema bootstrap migration, configure test suites with dedicated PostgreSQL support, and provide verification commands.

#### What Was Implemented:
1. **SQLAlchemy 2.x Persistence Base ([app/db/base.py](app/db/base.py)):**
   - Implemented standard SQLAlchemy 2.x `DeclarativeBase` subclass (`Base`) for all future domain models.
2. **Async Engine & Session Management ([app/db/session.py](app/db/session.py)):**
   - **Singleton Engine:** Configured `create_async_engine` using `settings.database_url`, connection pool options (`db_pool_size`, `db_max_overflow`, `db_pool_timeout`), and connection liveness pre-ping (`pool_pre_ping=True`).
   - **Async Session Factory:** Configured `async_sessionmaker` with `expire_on_commit=False` and `autoflush=False`.
   - **Connection Pool Disposal:** Implemented `close_database_connections()` integrated into FastAPI application `lifespan` handler for graceful resource cleanup on shutdown.
3. **Dependency-Injected Session Lifecycle (`get_db_session`):**
   - Implemented generator dependency yielding an `AsyncSession`.
   - Automatically commits active transactions on successful completion.
   - Automatically executes rollback if an unhandled exception occurs inside the handler/service.
   - Guarantees session closure in a `finally` block to prevent connection leaks.
4. **Database Readiness Probe ([app/api/v1/endpoints/health.py](app/api/v1/endpoints/health.py)):**
   - Implemented `check_database_connection()`: executes lightweight `SELECT 1` with a 3.0s timeout. Catches failures and logs only the exception class without logging connection URLs or passwords.
   - Implemented `GET /health/ready`: returns HTTP 200 `{"status": "ok", "database": "connected"}` when healthy.
   - If database is unavailable, raises `ServiceUnavailableError`, returning standard HTTP 503 response envelope (`SERVICE_UNAVAILABLE`) with **zero connection strings, passwords, or hostnames leaked**.
5. **Alembic Migrations Wired to Settings ([alembic.ini](alembic.ini) & [alembic/](alembic/)):**
   - **`alembic.ini`:** Configured with dynamic URL placeholder and standard migration metadata.
   - **`alembic/env.py`:** Configured to dynamically source database connection URLs from application `Settings` (or `-x db_url=...` / `DATABASE_URL` environment variables). Wired `target_metadata` to `Base.metadata`.
   - **Bootstrap Migration Revision ([alembic/versions/0001_initial_bootstrap.py](alembic/versions/0001_initial_bootstrap.py)):** Minimal verification migration creating `_schema_bootstrap_probe` table with timezone-aware `created_at` timestamp and primary key, with matching clean downgrade.
6. **Dedicated Test Suite & PostgreSQL Integration ([tests/test_database.py](tests/test_database.py) & [tests/conftest.py](tests/conftest.py)):**
   - `test_settings_database_url_and_pool_config`: Validates asyncpg URL format and pool settings.
   - `test_engine_initialization_singleton`: Validates engine caching and pool options.
   - `test_session_factory_singleton`: Validates sessionmaker flags (`expire_on_commit=False`).
   - `test_session_lifecycle_commits_on_success`: Validates auto-commit behavior on success.
   - `test_session_lifecycle_rolls_back_on_exception`: Validates rollback behavior on exceptions.
   - `test_check_database_connection_returns_false_on_failure`: Verifies exception catching and credential redaction.
   - `test_health_ready_endpoint_healthy`: Verifies HTTP 200 payload.
   - `test_health_ready_endpoint_unhealthy_returns_503_without_credentials_leak`: Verifies HTTP 503 error envelope and confirms absence of leaked connection strings.
   - `test_alembic_configuration_wired_to_settings`: Validates migration heads and metadata wiring.
   - `test_alembic_offline_migration_sql_generation`: Programmatically generates dry-run transactional SQL.
   - `test_live_postgres_connectivity_and_migration`: Live PostgreSQL integration test executing against `TEST_DATABASE_URL` when PostgreSQL is active (skipped gracefully with documented reason when no PostgreSQL service is running).

---

## Step-by-Step Verification Guide for Milestone 05

Follow these instructions to verify every part of Milestone 05 locally:

### Step 1: Run Ruff Linter
Verify code style, typing, and import ordering:
```powershell
.\.venv\Scripts\ruff check .
```
**Expected Output:**
```
All checks passed!
```

---

### Step 2: Run Ruff Format Check
Verify consistent formatting across all codebase files:
```powershell
.\.venv\Scripts\ruff format --check .
```
**Expected Output:**
```
40 files already formatted
```

---

### Step 3: Run the Complete Test Suite
Execute Pytest across all test suites:
```powershell
.\.venv\Scripts\pytest -v
```
**Expected Output:**
```
tests/test_container_config.py::test_dockerfile_exists_and_configured PASSED    [  3%]
tests/test_container_config.py::test_dockerignore_configuration PASSED          [  6%]
tests/test_container_config.py::test_docker_compose_services_and_healthchecks PASSED [  9%]
tests/test_database.py::test_settings_database_url_and_pool_config PASSED      [ 12%]
tests/test_database.py::test_engine_initialization_singleton PASSED            [ 15%]
tests/test_database.py::test_session_factory_singleton PASSED                  [ 18%]
tests/test_database.py::test_session_lifecycle_commits_on_success PASSED       [ 21%]
tests/test_database.py::test_session_lifecycle_rolls_back_on_exception PASSED [ 24%]
tests/test_database.py::test_check_database_connection_returns_false_on_failure PASSED [ 27%]
tests/test_database.py::test_health_ready_endpoint_healthy PASSED              [ 30%]
tests/test_database.py::test_health_ready_endpoint_unhealthy_returns_503_without_credentials_leak PASSED [ 33%]
tests/test_database.py::test_alembic_configuration_wired_to_settings PASSED   [ 36%]
tests/test_database.py::test_alembic_offline_migration_sql_generation PASSED   [ 39%]
tests/test_database.py::test_live_postgres_connectivity_and_migration SKIPPED (Live PostgreSQL not reachable) [ 42%]
tests/test_errors.py::test_not_found_error_response_shape PASSED                [ 45%]
...
================== 32 passed, 1 skipped, 1 warning in 2.50s ===================
```

---

### Step 4: Verify Alembic Offline Migration SQL Generation
Verify that Alembic generates clean transactional PostgreSQL DDL without requiring a running database:
```powershell
.\.venv\Scripts\alembic upgrade head --sql
```
**Verify:** Output begins with `BEGIN;`, defines table `_schema_bootstrap_probe`, updates `alembic_version`, and ends with `COMMIT;`.

---

### Step 5: Verify Application Readiness Endpoint Under Inactive DB
Start the development server and test readiness probe behavior:
```powershell
# In terminal 1:
.\.venv\Scripts\uvicorn app.main:app --reload

# In terminal 2:
curl.exe -i http://127.0.0.1:8000/health/ready
```
**Expected Response:** HTTP 503 Service Unavailable with JSON error envelope and no credentials:
```json
{
  "error": {
    "code": "SERVICE_UNAVAILABLE",
    "message": "Database service is unavailable.",
    "request_id": "req_..."
  }
}
```

---

### Step 6: Create the Milestone 05 Git Commit
Once verified, stage and commit Milestone 05:
```bash
git add pyproject.toml app/ tests/ alembic.ini alembic/ README.md PROGRESS.md
git commit -m "feat: add PostgreSQL persistence and Alembic migrations"
```

---

### Milestone 06: Core Telemedicine Database Models
- **Commit Message:** `feat: add core telemedicine database models`
- **Scope:** Implement SQLAlchemy 2.x declarative models and Alembic migration `0002_create_core_models` for all 11 core tables specified in [docs/data-model.md](docs/data-model.md) and [docs/diagrams/er-diagram.mmd](docs/diagrams/er-diagram.mmd). Enforce UUID primary keys, UTC timezone-aware timestamps, foreign keys with deletion rules preserving medical history, exact integer minor monetary representation, partial unique indexes preventing slot double-booking, and comprehensive model invariant tests.

#### What Was Implemented:
1. **User and Profile Models ([app/models/user.py](app/models/user.py)):**
   - `User`: UUID primary key (`gen_random_uuid()`), normalized unique email (`email_normalized`), password hash (Argon2id), role enum (`patient`, `doctor`, `admin`), activation status, MFA fields (`mfa_enabled`, `mfa_secret_encrypted`), and UTC timestamps.
   - `Profile`: 1-to-1 relationship with `User` (`user_id` FK on delete `CASCADE`), `full_name`, `phone`, `date_of_birth`, and UTC timestamps.
2. **Doctor and Availability Slot Models ([app/models/doctor.py](app/models/doctor.py)):**
   - `Doctor`: 1-to-1 relationship with `User` (`user_id` FK on delete `CASCADE`), unique `license_number`, `specialization`, verification status, integer minor unit consultation fee (`consultation_fee_minor >= 0` check constraint), currency (`INR`), bio, and UTC timestamps.
   - `AvailabilitySlot`: doctor relationship (`doctor_id` FK on delete `CASCADE`), `start_at`, `end_at`, interval check constraint (`end_at > start_at`), status (`available`, `booked`, `blocked`), and composite index `(doctor_id, start_at, status)`.
3. **Consultations Model ([app/models/consultation.py](app/models/consultation.py)):**
   - `Consultation`: referential integrity to `users.id` (`patient_id` on delete `RESTRICT`), `doctors.id` (`doctor_id` on delete `RESTRICT`), and `availability_slots.id` (`slot_id` on delete `RESTRICT`).
   - **Concurrency-Safe Atomic Booking Constraint:** Enforced partial unique index `uq_consultations_active_slot` on `slot_id WHERE status NOT IN ('cancelled')` to eliminate double-booking at the PostgreSQL database level.
4. **Prescription and Item Models ([app/models/prescription.py](app/models/prescription.py)):**
   - `Prescription`: unique 1-to-1 relationship with `consultations.id` on delete `RESTRICT`, referential integrity with patient and doctor on delete `RESTRICT`, clinical notes, `issued_at`, and UTC timestamps.
   - `PrescriptionItem`: child line item entity with `prescription_id` FK on delete `CASCADE`, medicine name, dosage, route, frequency, duration, and instructions.
5. **Payment Model ([app/models/payment.py](app/models/payment.py)):**
   - `Payment`: associated consultation (`consultation_id` on delete `RESTRICT`), non-negative amount constraint (`amount_minor >= 0`), currency, status, provider name, and unique partial index on `provider_reference WHERE provider_reference IS NOT NULL`.
6. **Audit and Idempotency Models ([app/models/audit.py](app/models/audit.py) & [app/models/idempotency.py](app/models/idempotency.py)):**
   - `AuditLog`: tamper-evident log capturing `actor_user_id` (on delete `SET NULL` so audit history survives account deletion), action, resource type, resource UUID, correlation ID, and JSONB metadata.
   - `IdempotencyKey`: tied to `users.id` on delete `CASCADE`, composite unique constraint `uq_idempotency_user_key_operation` on `(user_id, key, operation)`, request payload SHA-256 hash, execution status, response code, and JSONB response payload.
7. **Transactional Outbox Event Model ([app/models/outbox.py](app/models/outbox.py)):**
   - `OutboxEvent`: decoupled event publication entity storing `event_type`, `aggregate_type`, `aggregate_id`, JSONB payload, status, retry attempt counter, and error trace.
8. **Core Alembic Migration Revision ([alembic/versions/0002_create_core_models.py](alembic/versions/0002_create_core_models.py)):**
   - Migration chained to `0001_initial_bootstrap`.
   - Generates full PostgreSQL DDL for all 11 tables with constraints and indexes, with clean reverse-dependency downgrade.
9. **Automated Schema Invariant Tests ([tests/test_models.py](tests/test_models.py)):**
   - Validates that all 11 tables are registered in `Base.metadata`.
   - Validates UUID primary keys across all models.
   - Validates non-cascade delete rules protecting medical and financial history (`RESTRICT` on consultations, prescriptions, payments; `SET NULL` on audit logs).
   - Validates check constraints (`chk_doctors_fee_non_negative`, `chk_slot_time_interval`, `chk_payments_amount_non_negative`).
   - Validates unique and partial unique indexes (`uq_consultations_active_slot`, `uq_payments_provider_reference`, `uq_idempotency_user_key_operation`).
   - Validates Python column defaults and clean model instantiation.

---

## Step-by-Step Verification Guide for Milestone 06

Follow these instructions to verify every part of Milestone 06 locally:

### Step 1: Run Ruff Linter
Verify code style, typing, and import ordering across all models and tests:
```powershell
.\.venv\Scripts\ruff check .
```
**Expected Output:**
```
All checks passed!
```

---

### Step 2: Run Ruff Format Check
Verify consistent formatting across all 51 codebase files:
```powershell
.\.venv\Scripts\ruff format --check .
```
**Expected Output:**
```
51 files already formatted
```

---

### Step 3: Run the Complete Test Suite
Execute Pytest across all test suites (settings, logging, middleware, health, container config, database persistence, and models):
```powershell
.\.venv\Scripts\pytest -v
```
**Expected Output:**
```
tests/test_container_config.py::test_dockerfile_exists_and_configured PASSED    [  2%]
tests/test_container_config.py::test_dockerignore_configuration PASSED          [  5%]
tests/test_container_config.py::test_docker_compose_services_and_healthchecks PASSED [  7%]
tests/test_database.py::test_settings_database_url_and_pool_config PASSED      [ 10%]
...
tests/test_models.py::test_all_11_core_tables_registered_in_metadata PASSED    [ 72%]
tests/test_models.py::test_primary_keys_are_uuid PASSED                         [ 75%]
tests/test_models.py::test_foreign_key_delete_rules_prevent_history_erasure PASSED [ 77%]
tests/test_models.py::test_check_constraints_defined PASSED                    [ 80%]
tests/test_models.py::test_unique_indexes_and_partial_indexes PASSED            [ 82%]
tests/test_models.py::test_model_column_defaults_and_instantiation PASSED      [ 85%]
tests/test_models.py::test_live_postgres_model_operations SKIPPED (Live PostgreSQL not reachable) [ 87%]
...
================== 38 passed, 2 skipped, 1 warning in 4.60s ===================
```

---

### Step 4: Verify Alembic Migration Head and Offline SQL Generation
Confirm Alembic script directory recognizes revision `0002_create_core_models` as head:
```powershell
.\.venv\Scripts\alembic heads
```
**Expected Output:**
```
0002_create_core_models (head)
```

Generate dry-run static SQL to verify transactional PostgreSQL compilation:
```powershell
.\.venv\Scripts\alembic upgrade head --sql
```
**Verify:** Output generates `CREATE TABLE users`, `CREATE TABLE doctors`, `CREATE TABLE consultations` with `uq_consultations_active_slot`, and updates `alembic_version` to `0002_create_core_models`.

---

### Step 5: Create the Milestone 06 Git Commit
Once verified, stage and commit Milestone 06:
```bash
git add app/ alembic/ tests/ PROGRESS.md
git commit -m "feat: add core telemedicine database models"
```

---

### Milestone 07: User Registration & Argon2 Password Hashing
- **Commit Message:** `feat: add user registration and secure password hashing`
- **Scope:** Implement `POST /api/v1/auth/register` for patient registration and safe profile creation. Use a maintained Argon2 password hashing library (`argon2-cffi`), normalize email consistently, validate inputs with Pydantic, and enforce unique email in PostgreSQL. Return a response schema that cannot expose password hash, MFA secret, or internal-only fields. Use one transaction for user/profile creation and return a clean conflict for duplicate email. Add unit/API tests for valid registration, duplicate email, invalid payload, rollback behavior where practical, and response redaction. Do not add login/JWT in this commit.

#### What Was Implemented:
1. **Argon2id Password Hashing & Email Normalization ([app/core/security.py](app/core/security.py)):**
   - Implemented `hash_password()` using `argon2.PasswordHasher` configured with RFC 9106 and OWASP-recommended parameters: `time_cost=3`, `memory_cost=65536` (64 MiB), `parallelism=4`, `hash_len=32`, and `salt_len=16`.
   - Generates distinct salted hashes on every invocation even for identical passwords.
   - Implemented `verify_password()` with graceful error handling (`VerifyMismatchError`, `VerificationError`, `InvalidHashError`) returning a boolean without crashing or leaking details.
   - Implemented `normalize_email()` providing lowercase transformation and whitespace stripping.
2. **Input Validation and Redacted Response Schemas ([app/schemas/auth.py](app/schemas/auth.py)):**
   - `UserRegisterRequest`: Validates `email` with `EmailStr` and normalizes input; enforces `password` length between 8 and 128 characters and rejects whitespace-only passwords; validates non-blank `full_name`; validates optional `phone` and `date_of_birth` (rejecting future dates).
   - `ProfileResponse`: Serializes public profile demographic fields (`id`, `full_name`, `phone`, `date_of_birth`, UTC timestamps).
   - `UserResponse`: Maps `email_normalized` to public API field `email` via `validation_alias`. **Strictly omits** `password_hash`, `mfa_secret_encrypted`, and internal columns.
3. **Atomic Registration Business Service ([app/services/auth_service.py](app/services/auth_service.py)):**
   - `register_user(session, payload)`:
     - Pre-checks `select(User.id).where(User.email_normalized == email)` for existing accounts, returning clean `ConflictError(code="EMAIL_ALREADY_EXISTS")`.
     - Hashes password with Argon2id prior to database entity insertion.
     - Creates `User` with default `'patient'` role and active status.
     - Creates child `Profile` in the same database transaction.
     - Catches `IntegrityError` to handle concurrent duplicate email race conditions and executes immediate session rollback before raising `ConflictError`.
     - Ensures that if profile creation fails, the entire transaction is rolled back, preventing orphaned user accounts.
     - Logs registration success using `user_id` and `role` without leaking passwords or email PHI.
4. **Auth Endpoints & API Router Wiring ([app/api/v1/endpoints/auth.py](app/api/v1/endpoints/auth.py) & [app/api/v1/router.py](app/api/v1/router.py)):**
   - Implemented `POST /api/v1/auth/register` returning HTTP 201 Created on success, HTTP 409 Conflict on duplicate email, and HTTP 422 on validation failure.
   - Mounted `auth.router` under `api_v1_router` at prefix `/auth`.
5. **Relationship Loading Enhancement ([app/models/user.py](app/models/user.py)):**
   - Configured `lazy="selectin"` on `User.profile` to permit clean async serialization without requiring synchronous greenlet queries.
6. **Package Dependencies ([pyproject.toml](pyproject.toml)):**
   - Added maintained dependencies `"argon2-cffi>=23.1.0,<24.0.0"` and `"email-validator>=2.2.0,<3.0.0"`.
7. **Comprehensive Test Suite (16 new tests in [tests/test_auth.py](tests/test_auth.py)):**
   - Password hashing and unique salt verification.
   - Rejection of empty passwords and corrupt hash verification handling.
   - Email normalization unit tests.
   - Pydantic schema rejection for short passwords, whitespace passwords, blank names, and future dates of birth.
   - Response redaction verification asserting `password_hash` and `mfa_secret` are never present in response JSON.
   - Service layer test for clean user and profile persistence.
   - Service layer test for duplicate email pre-check conflict.
   - Service layer test for concurrent race condition rollback on `IntegrityError`.
   - Service layer test proving transaction rollback when profile insertion fails.
   - API integration tests via `TestClient` verifying HTTP 201, HTTP 409 with error envelope, and HTTP 422 with validation errors.
   - Live PostgreSQL integration test for real database constraint enforcement when PostgreSQL is reachable.

---

## Step-by-Step Verification Guide for Milestone 07

Follow these instructions to verify every part of Milestone 07 locally:

### Step 1: Run Ruff Linter
Verify code style, typing, and import ordering across all models, services, endpoints, and tests:
```powershell
.\.venv\Scripts\ruff check .
```
**Expected Output:**
```
All checks passed!
```

---

### Step 2: Run Ruff Format Check
Verify consistent formatting across all 58 repository files:
```powershell
.\.venv\Scripts\ruff format --check .
```
**Expected Output:**
```
58 files already formatted
```

---

### Step 3: Run the Complete Test Suite
Execute Pytest across all test suites:
```powershell
.\.venv\Scripts\pytest -v
```
**Expected Output:**
```
tests/test_auth.py::test_hash_password_produces_valid_argon2id_hash PASSED       [  1%]
tests/test_auth.py::test_hash_password_rejects_empty PASSED                      [  3%]
tests/test_auth.py::test_verify_password_valid_and_mismatch PASSED               [  5%]
tests/test_auth.py::test_verify_password_handles_corrupt_hash_gracefully PASSED  [  7%]
tests/test_auth.py::test_normalize_email PASSED                                  [  8%]
tests/test_auth.py::test_register_request_valid_and_normalized PASSED            [ 10%]
tests/test_auth.py::test_register_request_rejects_invalid_inputs PASSED          [ 12%]
tests/test_auth.py::test_user_response_redaction_guarantee PASSED                [ 14%]
tests/test_auth.py::test_register_user_service_success PASSED                   [ 16%]
tests/test_auth.py::test_register_user_service_duplicate_email_precheck PASSED   [ 17%]
tests/test_auth.py::test_register_user_service_integrity_error_triggers_rollback PASSED [ 19%]
tests/test_auth.py::test_register_user_service_rollback_on_profile_creation_failure PASSED [ 21%]
tests/test_api_register_valid_payload_returns_201_and_safe_response PASSED     [ 23%]
tests/test_api_register_duplicate_email_returns_409_conflict PASSED             [ 25%]
tests/test_api_register_invalid_payload_returns_422 PASSED                      [ 26%]
tests/test_live_postgres_registration_and_uniqueness_constraint SKIPPED        [ 28%]
...
================== 53 passed, 3 skipped, 1 warning in 7.20s ===================
```

---

### Step 4: Verify Live Endpoint Registration & Error Envelopes
Start the development server:
```powershell
.\.venv\Scripts\uvicorn app.main:app --reload
```

In a separate terminal or PowerShell prompt, test the registration flow:

1. **Verify OpenAPI Documentation Includes `/api/v1/auth/register`:**
   Open browser at: `http://127.0.0.1:8000/docs`
   Confirm `POST /api/v1/auth/register` appears with tag `auth`, request schema `UserRegisterRequest`, and response `UserResponse`.

2. **Test Validation Rejection (HTTP 422):**
   ```powershell
   curl.exe -i -X POST http://127.0.0.1:8000/api/v1/auth/register `
     -H "Content-Type: application/json" `
     -d '{"email":"invalid","password":"123","full_name":""}'
   ```
   **Expected Response:** HTTP 422 with standardized error envelope:
   ```json
   {
     "error": {
       "code": "VALIDATION_ERROR",
       "message": "Request validation failed.",
       "request_id": "req_...",
       "details": [...]
     }
   }
   ```

---

### Step 5: Create the Milestone 07 Git Commit
Once verified, stage and commit Milestone 07:
```bash
git add pyproject.toml app/ tests/ docs/security-checklist.md PROGRESS.md
git commit -m "feat: add user registration and secure password hashing"
```

