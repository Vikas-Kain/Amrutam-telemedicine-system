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
| **07** | User Registration & Argon2 Password Hashing | `feat: add user registration and secure password hashing` | **Completed & Committed** |
| **08** | JWT Authentication & Role-Based Authorization | `feat: add JWT authentication and role-based authorization` | **Implemented (Pending Commit)** |
| **09** | Doctor Profiles & Searchable Listing | `feat: add doctor profiles and search filters` | **Completed & Committed** |
| **10** | Doctor Availability Slot Management | `feat: add doctor availability management` | **Completed & Committed** |
| **11** | Idempotency Storage & Request Handling | `feat: add idempotency key persistence for write requests` | **Completed & Committed** |
| **12** | Atomic, Concurrency-Safe Booking Workflow | `feat: implement atomic idempotent appointment booking` | **Completed & Committed** |
| **13** | Booking Retrieval & Cancellation Lifecycle | `feat: add booking retrieval and cancellation lifecycle` | **Implemented (Pending Commit)** |
| **14** | Consultation Lifecycle State Machine | `feat: enforce consultation lifecycle transitions` | **Implemented (Pending Commit)** |
| **15** | Prescriptions & Item Authorization | `feat: add prescription and prescription-item workflows` | *Next Up* |
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

---

### Milestone 08: JWT Authentication & Role-Based Authorization
- **Commit Message:** `feat: add JWT authentication and role-based authorization`
- **Scope:** Implement login and safe access-token issuing/verification with short expiry and strict configuration. Validate signature, expiry and configured claims/algorithm; never accept a token-selected algorithm or log tokens. Add `get_current_user`, `require_roles`, and reusable authorization dependencies. Include `/api/v1/auth/me`. Resource ownership checks will be implemented with relevant feature services, so do not assume role checks alone authorize sensitive records. Add tests for bad credentials, inactive account, missing/invalid/expired token, allowed and denied role access, and safe response payloads. Ensure signing secrets come only from configuration.

#### What Was Implemented:
1. **JWT Generation & Strict Verification ([app/core/security.py](app/core/security.py)):**
   - Implemented `create_access_token(subject, role, expires_delta)` with standard RFC 7519 claims (`sub`, `role`, `iat`, `nbf`, `exp`, `jti`).
   - Implemented `decode_access_token(token)` enforcing signature verification, expiration check, and configured algorithm restriction (`algorithms=[settings.jwt_algorithm]`).
   - Strictly rejects `none` algorithm or algorithm-switching attacks. Never logs raw tokens.
2. **Authentication Schemas ([app/schemas/auth.py](app/schemas/auth.py)):**
   - `LoginRequest`: Validates normalized email and password length (1-128 chars).
   - `TokenResponse`: Returns `access_token`, `token_type="bearer"`, `expires_in` seconds, and sanitized `user` profile (`UserResponse`).
3. **Authentication Business Services ([app/services/auth_service.py](app/services/auth_service.py)):**
   - `authenticate_user()`: Verifies normalized email and password using Argon2id. Uses generic `INVALID_CREDENTIALS` (HTTP 401) to eliminate user enumeration. Enforces active account checks with `ACCOUNT_INACTIVE` (HTTP 403).
   - `get_user_by_id()`: Retrieves user by UUID with profile eagerly loaded via `selectinload`.
4. **Reusable Authorization Dependencies ([app/api/deps.py](app/api/deps.py)):**
   - `get_current_user`: Resolves bearer token from `Authorization: Bearer <token>` header; decodes and validates token; rejects missing/invalid tokens with standardized `UnauthorizedError` (HTTP 401) and inactive accounts with `ForbiddenError` (HTTP 403).
   - `require_roles(*allowed_roles)`: Dependency factory enforcing role-based access control. Returns `ForbiddenError("You do not have permission to perform this action.", code="INSUFFICIENT_PERMISSIONS")` (HTTP 403) on unauthorized roles.
   - Provided pre-configured dependency shortcuts: `require_doctor`, `require_admin`, `require_doctor_or_admin`, `require_patient`.
5. **API Endpoints ([app/api/v1/endpoints/auth.py](app/api/v1/endpoints/auth.py)):**
   - `POST /api/v1/auth/login`: Authenticates user and issues signed JWT bearer token.
   - `GET /api/v1/auth/me`: Returns sanitized user and demographic profile details for current authenticated caller.
6. **Automated Test Suite (27 test cases added in [tests/test_auth.py](tests/test_auth.py)):**
   - JWT token unit tests: creation, standard RFC claims, expiry rejection (`TOKEN_EXPIRED`), tampered signature rejection (`INVALID_TOKEN`), algorithm confusion rejection, missing claims rejection, settings secret validation.
   - Authentication service tests: valid credentials, bad password, non-existent email, inactive account rejection.
   - API endpoint tests: login success, bad credentials (401), missing user (401), inactive account (403), request validation error (422), `/auth/me` profile retrieval (200), missing token (401), invalid token (401), expired token (401), inactive user rejection (403).
   - Role authorization tests: authorized role access (200), unauthorized role denial (403), multi-role authorized access (200).
   - Live PostgreSQL integration test: verifies user registration, live password hash verification, and token generation end-to-end against live PostgreSQL.

---

### Step-by-Step Verification Guide for Milestone 08

Follow these instructions to verify Milestone 08 locally:

#### Step 1: Run Ruff Linter
Verify code style, typing, and import ordering:
```powershell
.\.venv\Scripts\ruff.exe check .
```
**Expected Output:**
```
All checks passed!
```

#### Step 2: Run Ruff Format Check
Verify consistent formatting across all codebase files:
```powershell
.\.venv\Scripts\ruff.exe format --check .
```
**Expected Output:**
```
63 files already formatted
```

#### Step 3: Run the Complete Test Suite
Execute Pytest across all test suites:
```powershell
.\.venv\Scripts\pytest.exe -v
```
**Expected Output:**
```
tests/test_auth.py .......................................               [ 42%]
...
======================== 91 passed, 1 warning in 3.50s ========================
```

#### Step 4: Verify Live Endpoints & Interactive OpenAPI Docs
Start the local development server:
```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

1. **Verify OpenAPI Documentation:**
   Open browser at `http://127.0.0.1:8000/docs`
   Confirm endpoints `POST /api/v1/auth/login` and `GET /api/v1/auth/me` are listed with tag `auth`.

2. **Test Login (HTTP 200):**
   ```powershell
   curl.exe -i -X POST http://127.0.0.1:8000/api/v1/auth/login `
     -H "Content-Type: application/json" `
     -d '{"email":"patient@example.com","password":"ValidPassword123!"}'
   ```
   **Expected Response:** HTTP 200 with `access_token`, `token_type: "bearer"`, and sanitized user object.

3. **Test Authenticated `/me` (HTTP 200):**
   ```powershell
   curl.exe -i http://127.0.0.1:8000/api/v1/auth/me `
     -H "Authorization: Bearer <your-access-token>"
   ```

---

### Milestone 09: Doctor Profiles & Searchable Doctor Listing
- **Commit Message:** `feat: add doctor profiles and search filters`
- **Scope:** Implement doctor profile read/search endpoints (`GET /api/v1/doctors` and `GET /api/v1/doctors/{doctor_id}`), including bounded pagination, deterministic sorting (`created_at DESC, id DESC`) and documented filters (`specialization`, `is_verified`, `name`, and `search`). Ensure only public fields are returned according to the API contract. Redact sensitive doctor license numbers, user credentials, and personal contact details. Add API tests for filtering, pagination bounds, ordering, missing doctor (404), and sensitive data redaction. Do not implement availability slot mutations.

#### What Was Implemented:
1. **Public Doctor Schemas ([app/schemas/doctor.py](app/schemas/doctor.py)):**
   - `DoctorPublicResponse`: Exposes only public information (`id`, `name`, `specialization`, `is_verified`, `consultation_fee_minor`, `currency`, `bio`, and UTC timestamps). **Strictly excludes** confidential license numbers, user account credentials, email, phone number, and internal identifiers.
   - `DoctorListResponse`: Standard pagination envelope containing `items`, `total`, `page`, `page_size`, and `total_pages`.
2. **Model Relationship Optimization ([app/models/doctor.py](app/models/doctor.py)):**
   - Configured `lazy="selectin"` on `Doctor.user` relationship for safe, non-blocking async query loading.
   - Added `@property def name(self) -> str` and `@property def full_name(self) -> str` to cleanly resolve the doctor's full name from `user.profile.full_name`.
3. **Doctor Search & Retrieval Business Services ([app/services/doctor_service.py](app/services/doctor_service.py)):**
   - `list_doctors()`:
     - Outer-joins `Doctor` with `User` and `Profile` to support queries and name retrieval.
     - Supports filters: `specialization` (case-insensitive substring), `is_verified` (boolean), `name` (case-insensitive substring), and general keyword `search` (matching across name, specialization, or bio).
     - Calculates total count and total pages dynamically using an identical count query.
     - Enforces deterministic sorting: `Doctor.created_at.desc(), Doctor.id.desc()`.
     - Applies bounded pagination via SQL `OFFSET` and `LIMIT`.
   - `get_doctor_by_id()`:
     - Retrieves a single doctor by UUID with associated user and profile.
     - Raises standard `NotFoundError("Doctor not found.", code="DOCTOR_NOT_FOUND")` when the requested doctor does not exist.
4. **API Endpoints & Routing ([app/api/v1/endpoints/doctors.py](app/api/v1/endpoints/doctors.py) & [app/api/v1/router.py](app/api/v1/router.py)):**
   - `GET /api/v1/doctors`: Supports search and filter parameters with strict pagination boundaries: `page >= 1` and `1 <= page_size <= 100` (rejecting queries outside these bounds with HTTP 422).
   - `GET /api/v1/doctors/{doctor_id}`: Returns public profile for a single doctor (HTTP 200) or HTTP 404 with standardized error envelope.
   - Mounted `doctors.router` under `api_v1_router` at prefix `/doctors`.
5. **Requirements Traceability Update ([docs/requirements-traceability.md](docs/requirements-traceability.md)):**
   - Marked "Search and filtering" requirement as `Implemented`.
6. **Comprehensive Automated Test Suite (12 tests in [tests/test_doctors.py](tests/test_doctors.py)):**
   - Schema invariant test asserting sensitive field redaction (license number, credentials, phone, email never exposed).
   - Service unit tests for `get_doctor_by_id` (success and 404) and `list_doctors` (pagination and sorting).
   - API integration tests via `TestClient` for:
     - Default pagination parameters (`page=1`, `page_size=20`).
     - Filtering by `specialization`, `is_verified`, `name`, and `search`.
     - Strict pagination limit validation (`page_size=101` -> 422, `page_size=0` -> 422, `page=0` -> 422).
     - Response redaction ensuring `license_number` is never present in HTTP response text.
     - Single doctor retrieval by ID (HTTP 200).
     - Non-existent doctor retrieval returning HTTP 404 with standard error envelope (`DOCTOR_NOT_FOUND`).
   - Live PostgreSQL integration test for query and filtering against live PostgreSQL.

---

## Step-by-Step Verification Guide for Milestone 09

Follow these instructions to verify every part of Milestone 09 locally:

### Step 1: Run Ruff Linter
Verify code style, typing, and import ordering across all models, services, endpoints, and tests:
```powershell
.\.venv\Scripts\ruff.exe check .
```
**Expected Output:**
```
All checks passed!
```

---

### Step 2: Run Ruff Format Check
Verify consistent formatting across all 62 repository files:
```powershell
.\.venv\Scripts\ruff.exe format --check .
```
**Expected Output:**
```
62 files already formatted
```

---

### Step 3: Run the Complete Test Suite
Execute Pytest across all test suites:
```powershell
.\.venv\Scripts\pytest.exe -v
```
**Expected Output:**
```
tests/test_auth.py ...............s                                      [ 23%]
tests/test_container_config.py ...                                       [ 27%]
tests/test_database.py ..........s                                       [ 44%]
tests/test_doctors.py ...........s                                       [ 61%]
tests/test_errors.py ....                                                [ 67%]
tests/test_health.py ...                                                 [ 72%]
tests/test_logging.py ..                                                 [ 75%]
tests/test_middleware.py ....                                            [ 80%]
tests/test_models.py ......s                                             [ 91%]
tests/test_settings.py ......                                            [100%]
================== 64 passed, 4 skipped, 1 warning in 9.30s ===================
```

---

### Step 4: Verify Live Endpoints & Interactive OpenAPI Docs
Start the local development server:
```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

In a second terminal or browser:

1. **Verify OpenAPI Documentation:**
   Open browser at `http://127.0.0.1:8000/docs`
   Confirm endpoints `GET /api/v1/doctors` and `GET /api/v1/doctors/{doctor_id}` are listed with tag `doctors`.

2. **Verify Doctor Listing with Default Pagination:**
   ```powershell
   curl.exe -i http://127.0.0.1:8000/api/v1/doctors
   ```
   **Expected Response:** HTTP 200 OK with `page=1`, `page_size=20`, `items=[]`, `total=0`, `total_pages=0`.

3. **Verify Pagination Boundary Rejection (HTTP 422):**
   ```powershell
   # Request exceeding max page_size (100)
   curl.exe -i "http://127.0.0.1:8000/api/v1/doctors?page_size=101"
   ```
   **Expected Response:** HTTP 422 with standardized `VALIDATION_ERROR` envelope.

4. **Verify Missing Doctor Retrieval (HTTP 404):**
   ```powershell
   curl.exe -i http://127.0.0.1:8000/api/v1/doctors/00000000-0000-0000-0000-000000000000
   ```
   **Expected Response:** HTTP 404 Not Found with error code `DOCTOR_NOT_FOUND`.

---

### Step 5: Create the Milestone 09 Git Commit
Once verified, stage and commit Milestone 09:
```bash
git add app/ tests/ docs/requirements-traceability.md PROGRESS.md
git commit -m "feat: add doctor profiles and search filters"
```

---

### Milestone 10: Doctor Availability Slot Management
- **Commit Message:** `feat: add doctor availability management`
- **Scope:** Provide endpoints to manage doctor availability slots (`POST /me/slots`, `PATCH /me/slots/{slot_id}`, `DELETE /me/slots/{slot_id}`, `GET /{doctor_id}/slots`), enforce slot authorization, reject invalid/past intervals and overlapping slots for the same doctor, protect booked slots, and enforce database-level constraints using PostgreSQL `btree_gist` exclusion constraints.

#### What Was Implemented:
1. **Database Migration (`alembic/versions/0003_slot_constraints_and_idx.py`):**
   - Enabled PostgreSQL `btree_gist` extension: `CREATE EXTENSION IF NOT EXISTS btree_gist;`.
   - Added `chk_availability_slots_status` check constraint enforcing valid statuses: `status IN ('available', 'booked', 'blocked')`.
   - Added range index `ix_availability_slots_doctor_range` on `(doctor_id, start_at, end_at)`.
   - Added GiST exclusion constraint `exclude_overlapping_doctor_slots`:
     ```sql
     ALTER TABLE availability_slots
     ADD CONSTRAINT exclude_overlapping_doctor_slots
     EXCLUDE USING gist (
         doctor_id WITH =,
         tstzrange(start_at, end_at) WITH &&
     );
     ```
   - Guaranteed at the database level that no doctor can ever have overlapping time intervals.

2. **SQLAlchemy Model Invariants (`app/models/doctor.py`):**
   - Updated `AvailabilitySlot.__table_args__` with `chk_availability_slots_status` and `ix_availability_slots_doctor_range`.

3. **Pydantic Schemas (`app/schemas/availability.py`):**
   - `SlotBase`: Base timestamps validator enforcing `end_at > start_at` and duration limits (10 minutes minimum, 4 hours maximum).
   - `SlotCreateRequest`: Single slot creation payload.
   - `SlotBatchCreateRequest`: Batch creation payload supporting between 1 and 50 slots per request.
   - `SlotUpdateRequest`: Updates slot status (`available` or `blocked`) or adjusts time intervals.
   - `SlotResponse`: Comprehensive slot representation including UUID, timestamps, status, and UTC audit dates.
   - `SlotListResponse`: Paginated or filtered slot list with total count.

4. **Business Services (`app/services/availability_service.py`):**
   - `get_doctor_by_user_id`: Safely resolves the Doctor entity from the authenticated User UUID.
   - `create_doctor_slots`: Rejects past timestamps (`PAST_SLOT_NOT_ALLOWED`), checks internal batch overlaps, performs pre-flight SQL overlap queries, inserts slots in an atomic transaction, and maps PostgreSQL exclusion violations (`IntegrityError`) to HTTP 409 `SLOT_OVERLAP`.
   - `list_doctor_slots`: Returns availability slots for a doctor with optional status filtering and UTC time window filtering.
   - `update_doctor_slot`: Verifies doctor ownership, prevents modification of booked slots (`SLOT_ALREADY_BOOKED`), and validates non-overlapping intervals when altering times.
   - `delete_doctor_slot`: Verifies doctor ownership, rejects deletion of booked slots (`SLOT_ALREADY_BOOKED`), and permanently removes unbooked slots.

5. **REST API Endpoints (`app/api/v1/endpoints/doctors.py`):**
   - `POST /api/v1/doctors/me/slots`: Doctor-authenticated endpoint creating single or batch availability slots (HTTP 201).
   - `PATCH /api/v1/doctors/me/slots/{slot_id}`: Doctor-authenticated endpoint modifying unbooked slot status or duration (HTTP 200).
   - `DELETE /api/v1/doctors/me/slots/{slot_id}`: Doctor-authenticated endpoint deleting an unbooked slot (HTTP 204).
   - `GET /api/v1/doctors/{doctor_id}/slots`: Public endpoint returning open and filtered slots for appointment discovery (HTTP 200).

6. **Comprehensive Test Suite (`tests/test_availability.py`):**
   - 23 automated tests covering:
     - Schema validation (inverted timestamps, duration limits, invalid statuses).
     - Service error handling (past slots, batch duplicates, booked slot modification protection, ownership checks).
     - Full HTTP API endpoint flows with JWT authentication.
     - Live PostgreSQL GiST exclusion constraint enforcement confirming database-level rejection of overlapping slots.

7. **Test Isolation Enhancement (`tests/conftest.py`):**
   - Added autouse `cleanup_db` fixture ensuring async database engines and connection pools are safely closed and reset between test executions across isolated event loops.

---

## Milestone 10 Verification Guide

### Step 1: Run Linting and Formatting
```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```
**Expected Output:**
```
All checks passed!
67 files already formatted
```

---

### Step 2: Run the Full Automated Test Suite
```powershell
.\.venv\Scripts\pytest.exe -v
```
**Expected Output:**
```
collected 114 items

tests\test_auth.py .......................................               [ 34%]
tests\test_availability.py .......................                       [ 54%]
tests\test_container_config.py ...                                       [ 57%]
tests\test_database.py ..........                                        [ 66%]
tests\test_doctors.py ............                                       [ 77%]
tests\test_errors.py ....                                                [ 80%]
tests\test_health.py ...                                                 [ 83%]
tests\test_logging.py ..                                                 [ 85%]
tests\test_middleware.py ....                                            [ 88%]
tests\test_models.py .......                                             [ 94%]
tests\test_settings.py ......                                            [100%]

======================= 114 passed, 1 warning in 3.34s =======================
```

---

### Step 3: Run Database Migrations on Live PostgreSQL
```powershell
.\.venv\Scripts\alembic.exe upgrade head
```
**Expected Output:**
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

---

### Step 4: Live HTTP API Verification with cURL / PowerShell
Start the application server:
```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

> [!TIP]
> In Windows PowerShell, when invoking `curl.exe` with JSON strings containing spaces and double quotes, prefix with `--%` (stop-parsing symbol) or use PowerShell's native `Invoke-RestMethod` to prevent PowerShell from stripping quotes.

1. **Register and Login as Doctor:**
   **Using `curl.exe` with stop-parsing token (`--%`):**
   ```powershell
   # Register doctor
   curl.exe --% -i -X POST http://127.0.0.1:8000/api/v1/auth/register -H "Content-Type: application/json" -d "{\"email\": \"dr.sharma@amrutam.co.in\", \"password\": \"StrongPassword123!\", \"full_name\": \"Dr. Sharma\", \"phone\": \"+919876543210\", \"role\": \"doctor\"}"

   # Login to get JWT
   $TOKEN = (curl.exe --% -s -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" -d "{\"email\": \"dr.sharma@amrutam.co.in\", \"password\": \"StrongPassword123!\"}" | ConvertFrom-Json).access_token
   ```

   **Or using native PowerShell `Invoke-RestMethod`:**
   ```powershell
   $body = @{
       email = "dr.sharma@amrutam.co.in"
       password = "StrongPassword123!"
       full_name = "Dr. Sharma"
       phone = "+919876543210"
       role = "doctor"
   } | ConvertTo-Json

   $reg = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/register" -ContentType "application/json" -Body $body
   $login = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/login" -ContentType "application/json" -Body (@{ email = "dr.sharma@amrutam.co.in"; password = "StrongPassword123!" } | ConvertTo-Json)
   $TOKEN = $login.access_token
   ```

2. **Create Availability Slots (Single or Batch):**
   ```powershell
   # Using curl.exe (escape inner quotes with \"):
   curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/doctors/me/slots" `
     -H "Authorization: Bearer $TOKEN" `
     -H "Content-Type: application/json" `
     -d '{\"start_at\":\"2026-11-01T09:00:00Z\",\"end_at\":\"2026-11-01T09:30:00Z\"}'

   # Or using Invoke-RestMethod:
   Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/doctors/me/slots" `
     -Headers @{ Authorization = "Bearer $TOKEN" } -ContentType "application/json" `
     -Body (@{ start_at = "2026-11-01T09:00:00Z"; end_at = "2026-11-01T09:30:00Z" } | ConvertTo-Json)
   ```
   **Expected Response:** HTTP 201 Created with JSON array containing the created slot.

3. **Verify Rejection of Overlapping Slot (HTTP 409):**
   ```powershell
   curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/doctors/me/slots" `
     -H "Authorization: Bearer $TOKEN" `
     -H "Content-Type: application/json" `
     -d '{\"start_at\":\"2026-11-01T09:15:00Z\",\"end_at\":\"2026-11-01T09:45:00Z\"}'
   ```
   **Expected Response:** HTTP 409 Conflict with `code: "SLOT_OVERLAP"`.

4. **Verify Rejection of Past Slot (HTTP 400):**
   ```powershell
   curl.exe -i -X POST "http://127.0.0.1:8000/api/v1/doctors/me/slots" `
     -H "Authorization: Bearer $TOKEN" `
     -H "Content-Type: application/json" `
     -d '{\"start_at\":\"2020-01-01T09:00:00Z\",\"end_at\":\"2020-01-01T09:30:00Z\"}'
   ```
   **Expected Response:** HTTP 400 Bad Request with `code: "PAST_SLOT_NOT_ALLOWED"`.

5. **Verify Public Slot Discovery:**
   Query the public availability endpoint using Dr. Sharma's doctor ID (`6e532162-74d6-4985-ba7e-02d8bde0624c`):
   ```powershell
   curl.exe -i "http://127.0.0.1:8000/api/v1/doctors/6e532162-74d6-4985-ba7e-02d8bde0624c/slots"
   ```
   **Expected Response:** HTTP 200 OK with total count and the list of active slots.

---

### Step 5: Live Test Execution Evidence

During manual interactive verification in PowerShell against the live server (`uvicorn app.main:app`), the following evidence was captured:

1. **Authentication & Token Retrieval:**
   ```powershell
   $login = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/login" -ContentType "application/json" -Body (@{ email = "dr.sharma@amrutam.co.in"; password = "StrongPassword123!" } | ConvertTo-Json)
   $TOKEN = $login.access_token
   ```

2. **Slot Creation (HTTP 201 Created via `Invoke-RestMethod`):**
   ```text
   id         : c18d9b89-6932-4fe0-bf90-e70f6dc66f9f
   doctor_id  : 6e532162-74d6-4985-ba7e-02d8bde0624c
   start_at   : 2026-11-01T14:00:00Z
   end_at     : 2026-11-01T14:30:00Z
   status     : available
   created_at : 2026-10-28T08:03:18.039759Z
   updated_at : 2026-10-28T08:03:18.039759Z
   ```

3. **Slot Creation (HTTP 201 Created via `curl.exe`):**
   ```json
   [{"id":"8c5235f4-38d3-405f-b1e9-1c651dc8cae5","doctor_id":"6e532162-74d6-4985-ba7e-02d8bde0624c","start_at":"2026-11-01T15:15:00Z","end_at":"2026-11-01T15:45:00Z","status":"available","created_at":"2026-10-28T08:03:56.683831Z","updated_at":"2026-10-28T08:03:56.683831Z"}]
   ```

4. **Rejection of Overlapping Slot (HTTP 409 Conflict):**
   ```json
   HTTP/1.1 409 Conflict
   {"error":{"code":"SLOT_OVERLAP","message":"Slot interval overlaps with an existing slot for this doctor.","request_id":"req_ebf8c1e9ce6a47e78650c02285b8350c"}}
   ```

5. **Public Slot Discovery (HTTP 200 OK):**
   ```json
   HTTP/1.1 200 OK
   {"items":[{"id":"86520041-3eb3-4d05-b11f-d2768f037747",...},{"id":"9a97d458-dcf6-4b04-bb65-cdd9ef5ebb0a",...},{"id":"b955ea53-cb31-4b51-a39b-bb50002caa00",...},{"id":"c18d9b89-6932-4fe0-bf90-e70f6dc66f9f",...},{"id":"8c5235f4-38d3-405f-b1e9-1c651dc8cae5",...}],"total":5}
   ```

---

### Step 6: Suggested Git Commit Command
Per `AGENTS.md`, commits are not made automatically by the agent. Review the diff and execute:
```bash
git add alembic/ app/ tests/ docs/ PROGRESS.md
git commit -m "feat: add doctor availability management"
```

---

### Milestone 11: Idempotency Storage & Request Handling
- **Commit Message:** `feat: add idempotency key persistence for write requests`
- **Scope:** Implement an idempotency service and persistence model for write operations. Scope keys to authenticated actor and operation, store a canonical request fingerprint (SHA-256), state and response/resource reference, enforce uniqueness in PostgreSQL, and define expiry/cleanup behavior. A matching completed request must replay the original outcome; same key with different payload must conflict (HTTP 409). Handle concurrent claims/unique constraint races without generic 500s or duplicate side effects. Add service/database tests, including concurrent same-key requests. Do not wire the service into booking until the next milestone, but make the interface usable and document its transaction expectations.

#### What Was Implemented:
1. **Database Migration (`alembic/versions/0004_idempotency_constraints.py`):**
   - Added check constraint `chk_idempotency_keys_status` enforcing valid lifecycle statuses: `status IN ('in_progress', 'completed', 'failed')`.
   - Added index `ix_idempotency_keys_expires_at` on `(expires_at)` for efficient cleanup queries.
   - Enforced database uniqueness via existing composite unique constraint `uq_idempotency_user_key_operation` on `(user_id, key, operation)`.

2. **SQLAlchemy Model Updates (`app/models/idempotency.py`):**
   - Updated `IdempotencyKey.__table_args__` with `chk_idempotency_keys_status` and `ix_idempotency_keys_expires_at`.
   - Maintained referential integrity with `users.id` on delete `CASCADE`.

3. **Pydantic Schemas (`app/schemas/idempotency.py`):**
   - `IdempotencyStatus`: `StrEnum` declaring lifecycle states (`in_progress`, `completed`, `failed`).
   - `IdempotencyResult`: Immutable result model representing claim/replay state, cached status code, JSON response body, and resource UUID.
   - `IdempotencyRecordResponse`: Inspection schema for audit and observability.

4. **Business Service (`app/services/idempotency_service.py`):**
   - `compute_request_hash`: Deterministic SHA-256 canonical fingerprinting supporting dictionaries, lists, strings, bytes, and Pydantic models with sorted keys and compact separators.
   - `validate_idempotency_key`: Enforces presence, whitespace trimming, and 255-character upper bound.
   - `claim_or_replay`:
     - Checks existing record by `(user_id, key, operation)`.
     - Detects expired keys (`expires_at <= now`) and resets them for a fresh claim.
     - Detects payload mutations and raises `ConflictError(code="IDEMPOTENCY_PAYLOAD_MISMATCH")` (HTTP 409).
     - Replays completed responses (`is_replayed=True`, `status="completed"`).
     - Protects active requests (`ConflictError(code="IDEMPOTENCY_CONCURRENT_REQUEST")`), while reclaiming orphaned claims older than the timeout threshold.
     - Uses nested transaction savepoints (`session.begin_nested()`) to atomically stage new claims; catches PostgreSQL `IntegrityError` races cleanly, rolls back the savepoint without aborting the outer transaction block, and safely inspects the winner's committed or active state.
   - `record_success`: Transitions an in-progress record to completed with its status code, JSON body, and resource UUID.
   - `record_failure`: Transitions an in-progress record to failed to allow subsequent user retries.
   - `cleanup_expired_keys`: Batch pruning of expired records.
   - `require_idempotency_key` & `optional_idempotency_key`: FastAPI header dependency extractors.

5. **Settings & Configuration (`app/core/config.py` & `.env.example`):**
   - Added `idempotency_default_ttl_seconds` (default: 86,400s / 24 hours).
   - Added `idempotency_in_progress_timeout_seconds` (default: 120s / 2 minutes).

6. **Comprehensive Test Suite (`tests/test_idempotency.py`):**
   - 23 dedicated automated unit, service, and live PostgreSQL integration tests:
     - Canonical fingerprinting invariance (ordering, nested structures, whitespace, Pydantic serialization).
     - Key validation and header dependency enforcement.
     - Single-transaction lifecycle (claim -> complete -> replay).
     - Payload tampering rejection (HTTP 409 `IDEMPOTENCY_PAYLOAD_MISMATCH`).
     - In-progress concurrency conflict rejection (HTTP 409 `IDEMPOTENCY_CONCURRENT_REQUEST`).
     - Expired key reset and reclamation of abandoned in-progress records.
     - Multi-tenant isolation (actor and operation scoping).
     - Live PostgreSQL concurrency stress test launching simultaneous async tasks racing on the identical key, proving zero 500 crashes and zero duplicate rows.

7. **Documentation Updates:**
   - Updated `docs/security-checklist.md` marking idempotency persistence control as implemented.
   - Updated `docs/requirements-traceability.md` tracking Milestone 11 completion.
   - Documented Single-Transaction and Two-Phase Transaction lifecycle patterns in `app/services/idempotency_service.py`.

---

## Milestone 11 Verification Guide

### Step 1: Run Linting and Formatting
```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```
**Expected Output:**
```
All checks passed!
71 files already formatted
```

---

### Step 2: Run the Full Automated Test Suite
```powershell
.\.venv\Scripts\pytest.exe -v
```
**Expected Output:**
```
collected 137 items

tests\test_auth.py .......................................               [ 28%]
tests\test_availability.py .......................                       [ 45%]
tests\test_container_config.py ...                                       [ 47%]
tests\test_database.py ...........                                       [ 55%]
tests\test_doctors.py ............                                       [ 64%]
tests\test_errors.py ....                                                [ 67%]
tests\test_health.py ...                                                 [ 69%]
tests\test_idempotency.py .......................                        [ 86%]
tests\test_logging.py ..                                                 [ 87%]
tests\test_middleware.py ....                                            [ 90%]
tests\test_models.py .......                                             [ 95%]
tests\test_settings.py ......                                            [100%]

======================= 137 passed, 1 warning in 3.41s ========================
```

---

### Step 3: Run Database Migrations on Live PostgreSQL
```powershell
.\.venv\Scripts\alembic.exe upgrade head
```
**Expected Output:**
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
0004_idempotency_constraints (head)
```

---

### Step 4: Suggested Git Commit Command
Per `AGENTS.md`, commits are not made automatically by the agent. Review the diff and execute:
```bash
git add alembic/ app/ tests/ docs/ .env.example PROGRESS.md
git commit -m "feat: add idempotency key persistence for write requests"
```

---

## Milestone 12: Atomic idempotent appointment booking

**Status:** Implemented and verified on local PostgreSQL.

- Added `POST /api/v1/bookings`, restricted to authenticated patients and requiring
  `Idempotency-Key`.
- Booking uses one request transaction to claim/replay idempotency, lock the selected slot,
  confirm its doctor and future/available state, create the consultation, mark the slot booked,
  store the completed response, and enqueue a minimal `booking.created` outbox event.
- PostgreSQL protects the workflow with `SELECT ... FOR UPDATE`, the existing partial unique
  active-consultation index, and a new composite foreign key enforcing slot-to-doctor ownership.
- A matching completed retry returns the stored booking with HTTP 200; changed payloads and
  availability conflicts return safe HTTP 409 responses. Clinical appointment reasons are not
  included in outbox payloads.
- Prompt 11 was additionally verified: idempotency reclaim operations lock an existing record,
  completed records cannot be overwritten, cleanup is bounded, and the PostgreSQL race tests pass.

### Verification run

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe upgrade head --sql
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\pytest.exe tests/test_bookings.py::test_live_postgres_competing_patients_create_one_booking_and_one_outbox_event -q
.\.venv\Scripts\pytest.exe tests/test_idempotency.py -q
.\.venv\Scripts\pytest.exe -q
```

All commands passed (149 tests). The full suite currently emits the pre-existing Starlette TestClient
deprecation warning for the installed HTTPX integration.

### Manual commit

Per `AGENTS.md`, no commit was created. Review the diff, then run:

```powershell
git add alembic/ app/ tests/ docs/ PROGRESS.md
git commit -m "feat: implement atomic idempotent appointment booking"
```

---

## Milestone 13: Booking retrieval and cancellation lifecycle

**Status:** Implemented and verified on local PostgreSQL.

- Added `GET /api/v1/bookings/{booking_id}` with service-enforced access for the owning patient,
  assigned doctor, or administrator.
- Added idempotent `POST /api/v1/bookings/{booking_id}/cancel`. It requires an
  `Idempotency-Key`; patients may cancel only their own future bookings in the `booked` state,
  while administrators may perform the same operational action.
- Cancellation preserves the consultation as `cancelled`, atomically returns its slot to
  `available`, stores the idempotent response, and persists a minimal `booking.cancelled` outbox
  event. A repeat cancellation returns the historical cancelled representation without a second
  event.
- No migration was required: the existing `cancelled` state and partial active-consultation index
  already permit a released slot to be rebooked while retaining booking history.

### Verification run

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe tests/test_bookings.py -q
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\alembic.exe upgrade head
```

All commands passed (157 tests). The full suite emits the existing Starlette TestClient deprecation
warning for the installed HTTPX integration.

### Manual commit

Per `AGENTS.md`, no commit was created. Review the diff, then run:

```powershell
git add app/ tests/ docs/ PROGRESS.md
git commit -m "feat: add booking retrieval and cancellation lifecycle"
```

---

## Milestone 14: Consultation lifecycle state machine

**Status:** Implemented and verified on local PostgreSQL.

- Created Alembic migration `0006_consultation_status_chk.py` adding check constraint `chk_consultations_status`
  enforcing valid consultation lifecycle statuses (`booked`, `confirmed`, `in_progress`, `completed`,
  `cancelled`, `no_show`) at the database level.
- Created `app/services/audit_service.py` exposing `record_audit_event` for recording tamper-evident audit
  logs in the active transaction without logging PHI or sensitive request bodies.
- Created `app/schemas/consultation.py` defining `ConsultationStatus` enum, `ConsultationResponse`, and
  bounded `ConsultationListResponse`.
- Implemented `app/services/consultation_service.py` providing:
  - `list_consultations`: strictly role-scoped (patients see only their own consultations, doctors see
    only assigned clinical appointments, admins view all with optional filters), supporting validated status
    filtering, deterministic sorting (`created_at DESC, id DESC`), and bounded pagination.
  - `get_consultation`: strictly authorizes patient owner, assigned doctor, or administrator.
  - `transition_consultation`: row-locking (`SELECT ... FOR UPDATE`) state machine enforcing allowed forward
    transitions (`booked` → `confirmed` → `in_progress` → `completed`, plus `confirmed` → `no_show`). Prevents
    clients from setting arbitrary statuses. Rejects cross-user or illegal transitions with 403/409, and enqueues
    an `OutboxEvent` and `AuditLog` within the same transaction.
- Implemented `app/api/v1/endpoints/consultations.py` mounting:
  - `GET /api/v1/consultations` (scoped listing)
  - `GET /api/v1/consultations/{id}` (authorized retrieval)
  - `POST /api/v1/consultations/{id}/confirm` (doctor/admin: booked → confirmed)
  - `POST /api/v1/consultations/{id}/start` (assigned doctor: confirmed → in_progress)
  - `POST /api/v1/consultations/{id}/complete` (assigned doctor: in_progress → completed)
  - `POST /api/v1/consultations/{id}/no-show` (doctor/admin: confirmed → no_show)
  - `POST /api/v1/consultations/{id}/cancel` (owner/admin: booked → cancelled with atomic slot release)
- Added `tests/test_consultations.py` with 27 unit and PostgreSQL integration tests verifying every allowed
  transition, rejected transition, cross-user denial, audit/outbox emission, concurrent transition serialization,
  and database status check constraint enforcement.

### Verification run

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\pytest.exe tests/test_consultations.py -v
.\.venv\Scripts\pytest.exe -v
```

All commands passed (184 total tests).

### Manual commit

Per `AGENTS.md`, no commit was created. Review the diff, then run:

```powershell
git add alembic/ app/ tests/ docs/ PROGRESS.md
git commit -m "feat: enforce consultation lifecycle transitions"
```


