"""Tests for Dockerfile, .dockerignore, and docker-compose.yml configurations."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent


def test_dockerfile_exists_and_configured():
    """Verify Dockerfile exists, uses multi-stage build, non-root user, and health check."""
    dockerfile_path = REPO_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"

    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage build targeting Python 3.12 slim
    assert "FROM python:3.12-slim-bookworm AS builder" in content
    assert "FROM python:3.12-slim-bookworm AS runtime" in content

    # Non-root user configuration
    assert "useradd" in content
    assert "appuser" in content
    assert "USER appuser" in content

    # No copying of .env or sensitive secrets
    assert "COPY .env" not in content
    assert "COPY *.env" not in content

    # Health check probe against liveness endpoint
    assert "HEALTHCHECK" in content
    assert "/health/live" in content

    # Clean Uvicorn startup
    assert 'CMD ["uvicorn", "app.main:app"' in content


def test_dockerignore_configuration():
    """Verify .dockerignore excludes sensitive files, environments, and caches."""
    dockerignore_path = REPO_ROOT / ".dockerignore"
    assert dockerignore_path.exists(), ".dockerignore must exist at repository root"

    content = dockerignore_path.read_text(encoding="utf-8")
    lines = {
        line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")
    }

    # Secrets and environment files
    assert ".env" in lines
    assert ".env.*" in lines
    assert "!.env.example" in lines

    # Caches and virtual environments
    assert any(".venv" in line for line in lines)
    assert any("__pycache__" in line for line in lines)
    assert any(".pytest_cache" in line for line in lines)
    assert any(".git" in line for line in lines)

    # Local database files
    assert any("*.db" in line or "*.sqlite" in line for line in lines)


def test_docker_compose_services_and_healthchecks():
    """Verify docker-compose.yml defines db and app services with health checks and volume."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist at repository root"

    with compose_path.open("r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    assert "services" in compose_data
    services = compose_data["services"]

    # Verify required services exist
    assert "db" in services, "db service must be defined in docker-compose.yml"
    assert "app" in services, "app service must be defined in docker-compose.yml"

    # Verify Redis is deferred as no active code/settings utilize it yet
    assert "redis" not in services, "Redis must be deferred until background/cache code needs it"

    # Verify db configuration
    db_service = services["db"]
    assert "postgres:16" in db_service.get("image", "")
    assert "healthcheck" in db_service
    db_healthcheck_test = str(db_service["healthcheck"].get("test", ""))
    assert "pg_isready" in db_healthcheck_test

    # Verify persistent volume on db
    db_volumes = db_service.get("volumes", [])
    assert any("pgdata" in str(v) for v in db_volumes)
    assert "volumes" in compose_data and "pgdata" in compose_data["volumes"]

    # Verify app configuration
    app_service = services["app"]
    assert "build" in app_service
    assert "depends_on" in app_service

    # App must wait for db to be healthy before starting
    depends_on_db = app_service["depends_on"].get("db", {})
    assert depends_on_db.get("condition") == "service_healthy", (
        "app service must wait for db condition: service_healthy"
    )

    # App must have liveness health check
    assert "healthcheck" in app_service
    app_healthcheck_test = str(app_service["healthcheck"].get("test", ""))
    assert "/health/live" in app_healthcheck_test

    # App command should not run automatic, unsafe migrations on worker startup
    app_command = str(app_service.get("command", ""))
    assert "alembic" not in app_command.lower(), "Unsafe auto-migrations must not run on app worker"
