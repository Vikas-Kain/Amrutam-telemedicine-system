# Deployment, Backup and Disaster Recovery

## 1. Local containerized development
Local development utilizes Docker Compose to run:
- **`app`**: FastAPI application running with Uvicorn (hot-reloading enabled for development).
- **`db`**: PostgreSQL 16 Alpine container with a dedicated persistent volume (`pgdata`).
- **`redis`**: (Optional) Redis 7 Alpine for shared rate-limiting or task queues.
- **`worker`**: Background worker process executing outbox event dispatch.
- **`prometheus` & `grafana`**: (Optional) Local telemetry stack.

### Secrets management
- Secrets and configuration are loaded from a local `.env` file excluded from Git.
- A template `.env.example` is maintained in the repository with non-sensitive placeholder values.

## 2. Container image hardening
- **Base image:** Use an official, pinned Python slim base image (e.g. `python:3.12-slim-bookworm`).
- **Non-root execution:** Create and switch to an unprivileged system user (e.g. `appuser:appgroup`).
- **Multi-stage build:** Compile wheels/dependencies in a builder stage and copy only the virtual environment into the minimal runtime stage.
- **No baked secrets:** Never copy `.env`, certificates, or private keys into the Docker image.
- **Signal handling:** Ensure PID 1 handles `SIGTERM` cleanly, allowing FastAPI/Uvicorn to drain active connections and close database pools before exit.
- **Explicit migrations:** Database migrations (`alembic upgrade head`) are run as an explicit one-off job or entrypoint step before traffic routing, not concurrently by multiple scaled replicas.

## 3. Continuous integration and delivery (CI/CD)

The GitHub Actions CI pipeline ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) automatically validates every push and pull request targeting `main`. It enforces strict least-privilege permissions (`contents: read`), uses non-production test credentials exclusively, and fails fast if any verification fails without suppressing valid findings.

### CI Pipeline Jobs

1. **`code-quality` (Format and Lint Check):**
   - Sets up Python 3.12 and installs Ruff.
   - Executes `ruff format --check .` to ensure formatting conformity.
   - Executes `ruff check .` to check for syntax bugs, unused imports, and style violations.
2. **`tests-and-migrations` (Unit & Integration Tests + Migrations):**
   - Spawns a real PostgreSQL 16 container service (`postgres:16-alpine`) with health check probes (`pg_isready`).
   - Runs `alembic upgrade head` to validate migration scripts against real PostgreSQL.
   - Runs `pytest -v` across the entire test suite, validating transactional guarantees, row-locking concurrency, and authorization boundaries.
   - Injects safe, dummy test credentials (`APP_ENV=test`, `SECRET_KEY=ci-insecure-test-...`, `MFA_ENCRYPTION_KEY=...`); zero production secrets are exposed.
3. **`security-scans` (Dependency Audit & Secret Scanning):**
   - Executes `pip-audit` to detect known CVEs in PyPI dependencies.
   - Runs Git repository inspection to ensure no `.env`, `.env.*`, `*.pem`, or `*.key` files are committed.
   - Runs TruffleHog OSS secret scanning to catch accidental API token or credential leaks.
4. **`container-build` (Docker Image Build & Hardening Verification):**
   - Builds the production multi-stage image (`Dockerfile`).
   - Inspects the container runtime UID to guarantee execution as unprivileged user (`appuser`, UID 10001, GID 10001).
   - Scans the container root filesystem to verify that `.env` files are not baked into the image.
   - Verifies the image `HEALTHCHECK` probe points to `/health/live`.

### Local Equivalent Commands

Developers must run these commands locally prior to opening pull requests:

```powershell
# 1. Formatting and linting
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .

# 2. Database migrations and tests (requires running local PostgreSQL)
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\pytest.exe -v

# 3. Dependency vulnerability audit
.\.venv\Scripts\pip-audit.exe

# 4. Secret & git hygiene check
git ls-files | Select-String -Pattern "^\.env$|^\.env\..+|.*\.pem$|.*\.key$"

# 5. Local Docker build and runtime verification
docker build -t amrutam-telemedicine:local .
docker run --rm amrutam-telemedicine:local id
docker run --rm amrutam-telemedicine:local sh -c "find /app -name '.env*'"
```

## 4. Production scaling outline
- **Stateless API tier:** Horizontal scaling of FastAPI replicas behind a managed load balancer (e.g. AWS ALB or NGINX) with TLS 1.3 termination.
- **Database tier:** Managed PostgreSQL (e.g. AWS RDS or GCP Cloud SQL) with Multi-AZ automated failover, read replicas for high-volume read endpoints, and pgBouncer connection pooling.
- **Worker tier:** Autoscaled Celery/async workers reading from the PostgreSQL outbox table or Redis stream.
- **Network isolation:** Private subnets for database and Redis instances; public access restricted to the HTTPS reverse proxy.

## 5. Backup and disaster recovery (DR)

### Recovery objectives
- **Recovery Point Objective (RPO):** Maximum acceptable data loss window: `< 15 minutes` in production (achieved via Continuous Write-Ahead Log / WAL archiving).
- **Recovery Time Objective (RTO):** Target recovery duration: `< 60 minutes` to restore complete service functionality.

### Backup schedule
- **Full database backup:** Daily encrypted snapshot stored in geographically replicated object storage (e.g. AWS S3 with SSE-KMS and versioning).
- **Continuous WAL archiving:** PostgreSQL WAL streaming to object storage enabling Point-in-Time Recovery (PITR) to any second within a 30-day retention window.
- **Backup encryption:** Backups encrypted with customer-managed keys (CMK) with strict IAM separation.

### Disaster recovery runbook
1. **Incident declaration:** Triage database outage or catastrophic data corruption; notify incident response team.
2. **Target environment setup:** Provision or isolate a clean PostgreSQL cluster in the designated recovery region.
3. **Snapshot and WAL restore:** Restore the latest base backup and replay WAL archives up to the desired point-in-time prior to the corruption/incident.
4. **Schema and migration verification:** Verify Alembic version table (`alembic_version`) matches the release tag.
5. **Integrity checks:** Run diagnostic scripts to check referential integrity across users, slots, consultations, and payment records.
6. **Key rotation:** If the disaster involved suspected credential compromise, immediately rotate JWT signing keys, database passwords, and provider webhook secrets.
7. **Service restoration:** Point API instances to the restored database, verify `/health/ready`, and run smoke tests on core booking workflows.
8. **Post-mortem documentation:** Document measured recovery time (actual RTO) and data variance (actual RPO) and update runbook.
