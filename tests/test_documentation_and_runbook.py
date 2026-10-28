"""Tests validating repository documentation integrity, OpenAPI export, and demo runbook."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"


def test_readme_exists_and_contains_no_unresolved_placeholders():
    """Verify README.md exists, reflects completed status, and links to all primary guides."""
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.exists(), "README.md must exist at repository root"

    content = readme_path.read_text(encoding="utf-8")

    # Must not contain stale placeholder status
    assert "Not started" not in content, "README must not contain 'Not started' placeholders"

    # Core required sections
    assert "## Architecture & System Invariants" in content
    assert "## Clean-Clone Setup Guide" in content
    assert "## Running the System" in content
    assert "## Interactive API Documentation & OpenAPI Export" in content
    assert "## Observability & Health Probes" in content
    assert "## Verification & Testing Commands" in content
    assert "## Five-Minute Evaluation Demo" in content
    assert "## Known Limitations & Design Boundaries" in content

    # Key referenced documents
    assert "docs/demo-script.md" in content
    assert "docs/architecture.md" in content
    assert "docs/api-contract.md" in content
    assert "docs/security-checklist.md" in content
    assert "docs/security-threat-model.md" in content
    assert "docs/deployment-and-recovery.md" in content


def test_demo_script_exists_and_covers_required_scenarios():
    """Verify docs/demo-script.md contains all 6 required demo verification steps."""
    demo_path = DOCS_DIR / "demo-script.md"
    assert demo_path.exists(), "docs/demo-script.md must exist"

    content = demo_path.read_text(encoding="utf-8")

    # Step 1: Health / Observability
    assert "/health/live" in content
    assert "/health/ready" in content

    # Step 4: Valid Booking
    assert "POST http://127.0.0.1:8000/api/v1/bookings" in content
    assert "Idempotency-Key" in content

    # Step 5: Duplicate Idempotent Retry
    assert "Duplicate Idempotent Retry" in content
    assert "X-Idempotent-Replay" in content

    # Step 6: Conflicting Booking Attempt
    assert "Conflicting Booking Attempt" in content
    assert "409 Conflict" in content
    assert "SLOT_NOT_AVAILABLE" in content

    # Step 7: Unauthorized IDOR Rejection
    assert "Unauthorized Access Rejection" in content
    assert "403 Forbidden" in content
    assert "FORBIDDEN" in content

    # Step 8: Consultation Lifecycle & Prescription
    assert "/confirm" in content
    assert "/prescriptions" in content
    assert "/complete" in content

    # Step 9: Prometheus Metrics
    assert "/metrics" in content


def test_openapi_json_schema_validity():
    """Verify docs/openapi.json exists, is valid JSON, and defines core routes."""
    openapi_path = DOCS_DIR / "openapi.json"
    assert openapi_path.exists(), "docs/openapi.json must exist"

    data = json.loads(openapi_path.read_text(encoding="utf-8"))
    assert "openapi" in data
    assert "paths" in data

    paths = data["paths"]
    # Health routes
    assert "/health/live" in paths
    assert "/health/ready" in paths

    # Auth routes
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths

    # Booking & consultation routes
    assert "/api/v1/bookings" in paths
    assert "/api/v1/consultations/{consultation_id}" in paths

    # Metrics route
    assert "/metrics" in paths


def test_security_checklist_reflects_completed_evidence():
    """Verify docs/security-checklist.md contains zero 'Not started' entries."""
    checklist_path = DOCS_DIR / "security-checklist.md"
    assert checklist_path.exists()

    content = checklist_path.read_text(encoding="utf-8")
    assert "Not started" not in content, "All controls must be Tested, Implemented, or Documented"
    assert "Tested" in content
    assert "tests/test_security.py" in content
    assert "tests/test_concurrency.py" in content
    assert "tests/test_rate_limiting.py" in content


def test_security_threat_model_stride_coverage():
    """Verify docs/security-threat-model.md covers all STRIDE categories with test references."""
    threat_path = DOCS_DIR / "security-threat-model.md"
    assert threat_path.exists()

    content = threat_path.read_text(encoding="utf-8")
    for category in [
        "Spoofing",
        "Tampering",
        "Repudiation",
        "Information Disclosure",
        "Denial of Service",
        "Elevation of Privilege",
    ]:
        assert category in content, f"STRIDE category '{category}' must be documented"

    assert "tests/test_auth.py" in content
    assert "tests/test_security.py" in content
    assert "tests/test_concurrency.py" in content


def test_mermaid_diagrams_exist_and_contain_diagram_definitions():
    """Verify Mermaid diagrams exist and define expected sequence and entity relationships."""
    sequence_path = DOCS_DIR / "diagrams" / "booking-sequence.mmd"
    er_path = DOCS_DIR / "diagrams" / "er-diagram.mmd"

    assert sequence_path.exists()
    assert er_path.exists()

    seq_content = sequence_path.read_text(encoding="utf-8")
    assert "sequenceDiagram" in seq_content
    assert "POST /api/v1/bookings" in seq_content
    assert "SELECT slot FOR UPDATE" in seq_content

    er_content = er_path.read_text(encoding="utf-8")
    assert "erDiagram" in er_content
    assert "USERS" in er_content
    assert "CONSULTATIONS" in er_content
    assert "OUTBOX_EVENTS" in er_content
