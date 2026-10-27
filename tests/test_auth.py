"""Tests for user registration, Argon2 password hashing, and response redaction."""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.errors import ConflictError
from app.core.security import hash_password, normalize_email, verify_password
from app.db.session import get_db_session
from app.main import create_app
from app.models.user import Profile, User
from app.schemas.auth import UserRegisterRequest, UserResponse
from app.services.auth_service import register_user
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from tests.conftest import is_postgres_available

# ==============================================================================
# 1. Cryptographic and Password Hashing Unit Tests
# ==============================================================================


def test_hash_password_produces_valid_argon2id_hash():
    """Verify password hasher produces Argon2id hashes with unique salts."""
    pwd = "CorrectHorseBatteryStaple123!"
    h1 = hash_password(pwd)
    h2 = hash_password(pwd)

    # Must be Argon2id algorithm format
    assert h1.startswith("$argon2id$")
    assert h2.startswith("$argon2id$")
    # Unique salts must ensure identical passwords yield different hashes
    assert h1 != h2


def test_hash_password_rejects_empty():
    """Verify hash_password raises ValueError for empty inputs."""
    with pytest.raises(ValueError, match="Password cannot be empty"):
        hash_password("")


def test_verify_password_valid_and_mismatch():
    """Verify verify_password returns True for match and False for mismatch."""
    pwd = "SuperSecretPassword42!"
    hashed = hash_password(pwd)

    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pwd, "") is False


def test_verify_password_handles_corrupt_hash_gracefully():
    """Verify verify_password does not raise unhandled exception on corrupted hash."""
    assert verify_password("somepassword", "$argon2id$corrupt_invalid_hash_string") is False


def test_normalize_email():
    """Verify email normalization lowercases and strips whitespace consistently."""
    assert normalize_email("  Test.User@EXAMPLE.com  ") == "test.user@example.com"
    assert normalize_email("PATIENT@Amrutam.CO.IN") == "patient@amrutam.co.in"
    assert normalize_email("") == ""


# ==============================================================================
# 2. Pydantic Request & Response Schema Tests
# ==============================================================================


def test_register_request_valid_and_normalized():
    """Verify UserRegisterRequest validates valid inputs and normalizes email."""
    req = UserRegisterRequest(
        email="  Patient.Aarav@EXAMPLE.COM ",
        password="ValidPassword123!",
        full_name="  Aarav Sharma  ",
        phone="+919876543210",
        date_of_birth=date(1995, 6, 20),
    )
    assert req.email == "patient.aarav@example.com"
    assert req.full_name == "Aarav Sharma"
    assert req.phone == "+919876543210"
    assert req.date_of_birth == date(1995, 6, 20)


def test_register_request_rejects_invalid_inputs():
    """Verify UserRegisterRequest enforces password length, non-blank name, and past DOB."""
    # Invalid email format
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="not-an-email",
            password="ValidPassword123!",
            full_name="Aarav Sharma",
        )

    # Password too short (< 8 characters)
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="patient@example.com",
            password="short",
            full_name="Aarav Sharma",
        )

    # Password whitespace-only
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="patient@example.com",
            password="        ",
            full_name="Aarav Sharma",
        )

    # Full name blank
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="patient@example.com",
            password="ValidPassword123!",
            full_name="   ",
        )

    # Future date of birth
    future_date = date.today() + timedelta(days=1)
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            email="patient@example.com",
            password="ValidPassword123!",
            full_name="Aarav Sharma",
            date_of_birth=future_date,
        )


def test_user_response_redaction_guarantee():
    """Verify UserResponse schema never leaks password_hash, MFA secret, or internal fields."""
    user = User(
        id=uuid.uuid4(),
        email_normalized="patient@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$dummyhash",
        role="patient",
        is_active=True,
        mfa_enabled=False,
        mfa_secret_encrypted="mfa_enc_secret_super_confidential",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    profile = Profile(
        id=uuid.uuid4(),
        user_id=user.id,
        full_name="Aarav Sharma",
        phone="+919876543210",
        date_of_birth=date(1990, 1, 1),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    user.profile = profile

    response_model = UserResponse.model_validate(user)
    serialized = response_model.model_dump(mode="json")

    # Safe fields must be present
    assert serialized["id"] == str(user.id)
    assert serialized["email"] == "patient@example.com"
    assert serialized["role"] == "patient"
    assert serialized["is_active"] is True
    assert serialized["mfa_enabled"] is False
    assert serialized["profile"]["full_name"] == "Aarav Sharma"

    # Strictly forbidden sensitive fields MUST NOT be present
    assert "password_hash" not in serialized
    assert "mfa_secret_encrypted" not in serialized
    assert "password" not in serialized
    assert "secret" not in serialized


# ==============================================================================
# 3. Service Layer and Rollback Unit Tests
# ==============================================================================


def _build_mock_session() -> AsyncMock:
    """Create a configured AsyncMock session with sync methods properly mocked."""
    session = AsyncMock()
    session.add = MagicMock()
    session.in_transaction = MagicMock(return_value=True)
    return session


@pytest.mark.asyncio
async def test_register_user_service_success():
    """Verify register_user creates User and Profile, hashes password, and commits."""
    session = _build_mock_session()
    # No existing user
    session.scalar.return_value = None

    payload = UserRegisterRequest(
        email="newuser@example.com",
        password="MyStrongPassword123!",
        full_name="Dr. Test",
        phone="+919999999999",
    )

    user = await register_user(session, payload)

    assert user.email_normalized == "newuser@example.com"
    assert user.role == "patient"
    assert user.is_active is True
    assert user.mfa_enabled is False
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password("MyStrongPassword123!", user.password_hash) is True
    assert user.profile is not None
    assert user.profile.full_name == "Dr. Test"
    assert session.commit.called


@pytest.mark.asyncio
async def test_register_user_service_duplicate_email_precheck():
    """Verify register_user raises ConflictError when email already exists."""
    session = _build_mock_session()
    # Existing user found
    session.scalar.return_value = uuid.uuid4()

    payload = UserRegisterRequest(
        email="existing@example.com",
        password="MyStrongPassword123!",
        full_name="Duplicate User",
    )

    with pytest.raises(ConflictError) as exc_info:
        await register_user(session, payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"
    assert not session.commit.called


@pytest.mark.asyncio
async def test_register_user_service_integrity_error_triggers_rollback():
    """Verify concurrent registration collision (IntegrityError) triggers rollback and 409."""
    session = _build_mock_session()
    session.scalar.return_value = None
    session.flush.side_effect = IntegrityError("duplicate key", params={}, orig=MagicMock())

    payload = UserRegisterRequest(
        email="race@example.com",
        password="MyStrongPassword123!",
        full_name="Race Candidate",
    )

    with pytest.raises(ConflictError) as exc_info:
        await register_user(session, payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"
    assert session.rollback.called
    assert not session.commit.called


@pytest.mark.asyncio
async def test_register_user_service_rollback_on_profile_creation_failure():
    """Verify that if profile creation fails, session rollback is executed."""
    session = _build_mock_session()
    session.scalar.return_value = None

    # First flush (User) succeeds, second flush (Profile) raises unexpected exception
    flush_count = 0

    async def flush_side_effect():
        nonlocal flush_count
        flush_count += 1
        if flush_count >= 2:
            raise RuntimeError("Database profile disk error")

    session.flush.side_effect = flush_side_effect

    payload = UserRegisterRequest(
        email="rollback@example.com",
        password="MyStrongPassword123!",
        full_name="Rollback Candidate",
    )

    with pytest.raises(RuntimeError, match="Database profile disk error"):
        await register_user(session, payload)

    assert session.rollback.called
    assert not session.commit.called


# ==============================================================================
# 4. API Endpoint Integration Tests (FastAPI TestClient)
# ==============================================================================


def test_api_register_valid_payload_returns_201_and_safe_response():
    """Verify POST /api/v1/auth/register creates user and returns HTTP 201 with redacted secrets."""
    app = create_app()

    mock_user_id = uuid.uuid4()
    mock_profile_id = uuid.uuid4()

    async def mock_get_db_session():
        session = _build_mock_session()
        session.scalar.return_value = None

        async def flush_side_effect():
            # Populate IDs on objects added to session
            for call_arg in session.add.call_args_list:
                obj = call_arg[0][0]
                if isinstance(obj, User):
                    obj.id = mock_user_id
                    obj.created_at = datetime.now(UTC)
                    obj.updated_at = datetime.now(UTC)
                elif isinstance(obj, Profile):
                    obj.id = mock_profile_id
                    obj.created_at = datetime.now(UTC)
                    obj.updated_at = datetime.now(UTC)

        session.flush.side_effect = flush_side_effect
        yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "  Patient.Ananya@Amrutam.in  ",
            "password": "SuperSafePassword2026!",
            "full_name": "  Ananya Patel  ",
            "phone": "+919876543210",
            "date_of_birth": "1992-04-12",
        },
    )

    assert response.status_code == 201
    data = response.json()

    assert data["id"] == str(mock_user_id)
    assert data["email"] == "patient.ananya@amrutam.in"  # Normalized
    assert data["role"] == "patient"
    assert data["is_active"] is True
    assert data["mfa_enabled"] is False
    assert data["profile"]["full_name"] == "Ananya Patel"
    assert data["profile"]["phone"] == "+919876543210"
    assert data["profile"]["date_of_birth"] == "1992-04-12"

    # Redaction checks
    raw_text = response.text
    assert "password_hash" not in raw_text
    assert "SuperSafePassword2026!" not in raw_text
    assert "mfa_secret" not in raw_text

    # Request ID header check
    assert "X-Request-ID" in response.headers


def test_api_register_duplicate_email_returns_409_conflict():
    """Verify duplicate email registration returns standard HTTP 409 error envelope."""
    app = create_app()

    async def mock_get_db_session():
        session = _build_mock_session()
        # Return existing user ID to trigger conflict
        session.scalar.return_value = uuid.uuid4()
        yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "ValidPassword123!",
            "full_name": "Duplicate User",
        },
    )

    assert response.status_code == 409
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "EMAIL_ALREADY_EXISTS"
    assert "already exists" in data["error"]["message"].lower()
    assert data["error"]["request_id"] is not None


def test_api_register_invalid_payload_returns_422():
    """Verify invalid payloads (short password, invalid email) return HTTP 422 error envelope."""
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "invalid-email-address",
            "password": "short",
            "full_name": "",
        },
    )

    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"


# ==============================================================================
# 5. Live PostgreSQL Integration Tests (Skipped when DB is unreachable)
# ==============================================================================


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_registration_and_uniqueness_constraint():
    """Verify registration, foreign keys, and unique constraint enforcement on live PostgreSQL."""
    unique_suffix = uuid.uuid4().hex[:8]
    test_email = f"test_patient_{unique_suffix}@example.com"
    pwd = "LivePostgresPassword123!"

    payload = UserRegisterRequest(
        email=test_email,
        password=pwd,
        full_name="Live Test Patient",
        phone="+919876543210",
        date_of_birth=date(1988, 8, 18),
    )

    # 1. Register first user successfully
    async for session in get_db_session():
        user = await register_user(session, payload)
        assert user.id is not None
        assert user.profile.id is not None
        assert user.profile.user_id == user.id
        break

    # 2. Attempt registration with duplicate email (different casing)
    duplicate_payload = UserRegisterRequest(
        email=test_email.upper(),  # Should normalize to same email
        password="DifferentPassword456!",
        full_name="Impostor User",
    )

    async for session in get_db_session():
        with pytest.raises(ConflictError) as exc_info:
            await register_user(session, duplicate_payload)
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"
        break
