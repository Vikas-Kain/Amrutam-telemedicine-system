"""Tests for GitHub Actions CI workflow configuration, security checks,
and container build validation.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_exists_and_is_valid_yaml():
    """Verify .github/workflows/ci.yml exists and parses as valid YAML."""
    assert CI_WORKFLOW_PATH.exists(), "GitHub Actions CI workflow file must exist"
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert isinstance(data, dict), "CI workflow must parse as a dictionary"
    assert "name" in data
    assert "on" in data
    assert "jobs" in data


def test_ci_workflow_triggers_and_least_privilege_permissions():
    """Verify CI workflow triggers on push/PR to main and enforces least-privilege permissions."""
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    # Trigger events
    on_triggers = data.get("on", {})
    assert "push" in on_triggers
    assert "main" in on_triggers["push"].get("branches", [])
    assert "pull_request" in on_triggers
    assert "main" in on_triggers["pull_request"].get("branches", [])

    # Least privilege permissions
    permissions = data.get("permissions", {})
    assert permissions.get("contents") == "read", "CI must have read-only contents permissions"


def test_ci_workflow_jobs_and_dependencies():
    """Verify all required CI pipeline jobs exist with appropriate dependencies."""
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    jobs = data.get("jobs", {})

    required_jobs = {"code-quality", "tests-and-migrations", "security-scans", "container-build"}
    for job_name in required_jobs:
        assert job_name in jobs, f"Job '{job_name}' must be defined in CI workflow"

    # Dependency ordering
    assert jobs["tests-and-migrations"].get("needs") == "code-quality"
    container_needs = jobs["container-build"].get("needs", [])
    assert "code-quality" in container_needs
    assert "tests-and-migrations" in container_needs


def test_ci_workflow_code_quality_job():
    """Verify code-quality job executes Ruff formatting and linting checks."""
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    steps = data["jobs"]["code-quality"]["steps"]

    step_runs = [step.get("run", "") for step in steps if "run" in step]
    all_runs = "\n".join(step_runs)

    assert "ruff format --check" in all_runs, "CI must verify formatting with ruff"
    assert "ruff check" in all_runs, "CI must verify linting with ruff"


def test_ci_workflow_tests_and_migrations_job():
    """Verify tests-and-migrations job uses PostgreSQL service and executes Alembic & Pytest."""
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    job = data["jobs"]["tests-and-migrations"]

    # PostgreSQL service container
    services = job.get("services", {})
    assert "postgres" in services, "PostgreSQL service must be defined for integration tests"
    postgres_svc = services["postgres"]
    assert "postgres:16" in postgres_svc.get("image", "")
    assert "pg_isready" in str(postgres_svc.get("options", ""))

    # Safe test environment configuration (no production secrets)
    env = job.get("env", {})
    assert env.get("APP_ENV") == "test"
    assert "ci-insecure-test" in env.get("SECRET_KEY", "")
    assert "localhost:5432" in env.get("DATABASE_URL", "")

    # Steps execution
    step_runs = "\n".join(s.get("run", "") for s in job["steps"] if "run" in s)
    assert "alembic upgrade head" in step_runs, "CI must run migrations before tests"
    assert "pytest -v" in step_runs, "CI must execute test suite with pytest"


def test_ci_workflow_security_scans_job():
    """Verify security-scans job audits dependencies, checks secrets, and avoids suppressions."""
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    job = data["jobs"]["security-scans"]
    steps = job["steps"]

    # Dependency vulnerability check
    step_runs = "\n".join(s.get("run", "") for s in steps if "run" in s)
    assert "pip-audit" in step_runs, "CI must audit dependencies with pip-audit"

    # Git secrets and .env check
    assert "git ls-files" in step_runs, "CI must verify no .env or key files are tracked"

    # Secret scanning action
    step_uses = [s.get("uses", "") for s in steps if "uses" in s]
    assert any("trufflehog" in u.lower() for u in step_uses), "CI must include secret scanning"


def test_ci_workflow_container_build_and_hardening_verification():
    """Verify container-build job verifies non-root UID, no .env inclusion, and health probe."""
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    job = data["jobs"]["container-build"]
    step_runs = "\n".join(s.get("run", "") for s in job["steps"] if "run" in s)

    # Non-root user verification
    assert "id -u" in step_runs, "CI must verify non-root user UID"

    # No .env leakage verification
    assert "find /app -name '.env*'" in step_runs, "CI must verify no .env baked in image"

    # Health check verification
    assert "health/live" in step_runs, "CI must verify container healthcheck probe"


def test_ci_workflow_does_not_suppress_failures():
    """Verify that CI steps do not use continue-on-error to suppress valid failures."""
    content = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    for job_name, job_data in data.get("jobs", {}).items():
        assert job_data.get("continue-on-error") is not True, (
            f"Job '{job_name}' must not have continue-on-error: true"
        )
        for step in job_data.get("steps", []):
            step_name = step.get("name", "unnamed")
            assert step.get("continue-on-error") is not True, (
                f"Step '{step_name}' in job '{job_name}' must not suppress failures"
            )


def test_git_repository_has_no_tracked_secrets_or_env_files():
    """Verify that no .env files or private keys are currently tracked in git."""
    import subprocess

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    for filename in tracked_files:
        assert filename != ".env", ".env must never be tracked in git"
        assert not filename.startswith(".env.") or filename == ".env.example", (
            f"Secret file {filename} must not be tracked in git"
        )
        assert not filename.endswith(".pem"), f"Certificate {filename} must not be tracked in git"
        assert not filename.endswith(".key"), f"Key file {filename} must not be tracked in git"
