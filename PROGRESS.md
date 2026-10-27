# Project Implementation Progress & Verification Guide

This document tracks the incremental implementation of the **Amrutam Telemedicine Backend** against the assignment requirements and the 25-milestone roadmap. It explains what has been built, the architectural rationale, and step-by-step verification procedures for each milestone.

---

## Overall Roadmap Status

| Milestone | Description | Commit Message | Status |
|:---:|---|---|:---:|
| **01** | Architecture & Project Implementation Plan | `docs: add architecture and project implementation plan` | **Completed & Committed** |
| **02** | Bootstrap FastAPI Package & Developer Tooling | `chore: bootstrap FastAPI application and developer tooling` | **Completed & Committed** |
| **03** | Settings, Structured Logging & API Error Handling | `feat: add application settings and structured error handling` | **Implemented (Pending Commit)** |
| **04** | Local PostgreSQL & Docker Development | `build: add Docker Compose development environment` | *Next Up* |
| **05** | SQLAlchemy Persistence & Alembic Migrations | `feat: add PostgreSQL persistence and Alembic migrations` | *Planned* |
| **06** | Core Database Models | `feat: add core telemedicine database models` | *Planned* |
| **07** | User Registration & Argon2 Password Hashing | `feat: add user registration and secure password hashing` | *Planned* |
| **08** | JWT Authentication & Role-Based Authorization | `feat: add JWT authentication and role-based authorization` | *Planned* |
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
