"""Tests for structured logging, redaction, and formatters."""

import json
import logging

from app.core.logging import (
    StructuredJsonFormatter,
    redact_sensitive_data,
    request_id_ctx_var,
)


def test_redact_sensitive_data_masks_passwords_and_tokens() -> None:
    """Verify sensitive fields are replaced with [REDACTED]."""
    payload = {
        "email": "doctor@amrutam.co",
        "password": "SuperSecretPassword123!",
        "token": "jwt.eyJhbGciOi...",
        "profile": {
            "full_name": "Dr. Ayush",
            "mfa_secret": "JBSWY3DPEHPK3PXP",
            "prescription_notes": "Take 5mg thrice daily",
        },
        "nested_list": [
            {"card_number": "4111222233334444", "status": "active"},
            {"public_info": "consultation_ready"},
        ],
    }

    sanitized = redact_sensitive_data(payload)

    assert sanitized["email"] == "doctor@amrutam.co"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["profile"]["full_name"] == "Dr. Ayush"
    assert sanitized["profile"]["mfa_secret"] == "[REDACTED]"
    assert sanitized["profile"]["prescription_notes"] == "[REDACTED]"
    assert sanitized["nested_list"][0]["card_number"] == "[REDACTED]"
    assert sanitized["nested_list"][0]["status"] == "active"
    assert sanitized["nested_list"][1]["public_info"] == "consultation_ready"


def test_structured_json_formatter_output() -> None:
    """Verify StructuredJsonFormatter emits parseable JSON with required audit metadata."""
    formatter = StructuredJsonFormatter(service_name="test-service", environment="test-env")

    token = request_id_ctx_var.set("req_logging_test_id")
    try:
        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="User %s logged in successfully",
            args=("user_123",),
            exc_info=None,
        )
        record.extra_fields = {"user_id": "user_123", "password": "should_be_masked"}

        formatted_output = formatter.format(record)
        parsed = json.loads(formatted_output)

        assert parsed["service"] == "test-service"
        assert parsed["environment"] == "test-env"
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "User user_123 logged in successfully"
        assert parsed["request_id"] == "req_logging_test_id"
        assert parsed["extra"]["user_id"] == "user_123"
        assert parsed["extra"]["password"] == "[REDACTED]"
    finally:
        request_id_ctx_var.reset(token)
