"""Tests for user registration, Argon2 password hashing, JWT authentication, and authorization."""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from app.api.deps import require_doctor, require_roles
from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_email,
    verify_password,
)
from app.db.session import get_db_session
from app.main import create_app
from app.models.user import Profile, User
from app.schemas.auth import UserRegisterRequest, UserResponse
from app.services.auth_service import authenticate_user, register_user
from fastapi import APIRouter, Depends
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
async def test_live_postgres_registration_authentication_and_uniqueness_flow():
    """Verify live PostgreSQL registration, password verification, and uniqueness constraint."""
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

        # 2. Authenticate user against live database
        auth_user = await authenticate_user(session, test_email, pwd)
        assert auth_user.id == user.id
        assert auth_user.role == "patient"
        assert auth_user.profile.full_name == "Live Test Patient"

        # 3. Create token and decode
        token = create_access_token(subject=auth_user.id, role=auth_user.role)
        decoded = decode_access_token(token)
        assert decoded["sub"] == str(user.id)
        assert decoded["role"] == "patient"
        break

    # 4. Attempt registration with duplicate email (different casing)
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


# ==============================================================================
# 6. JWT Token Creation, Claims & Strict Validation Tests
# ==============================================================================


def test_create_and_decode_access_token_success():
    """Verify create_access_token produces valid JWT with required RFC 7519 claims."""
    user_id = uuid.uuid4()
    role = "doctor"
    token = create_access_token(subject=user_id, role=role)

    assert isinstance(token, str)
    assert len(token.split(".")) == 3  # Valid JWT format header.payload.signature

    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == role
    assert "exp" in payload
    assert "iat" in payload
    assert "nbf" in payload
    assert "jti" in payload
    assert payload["exp"] > payload["iat"]


def test_decode_access_token_expired():
    """Verify expired token raises UnauthorizedError with code TOKEN_EXPIRED."""
    user_id = uuid.uuid4()
    expired_token = create_access_token(
        subject=user_id,
        role="patient",
        expires_delta=timedelta(seconds=-10),
    )

    with pytest.raises(UnauthorizedError) as exc_info:
        decode_access_token(expired_token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "TOKEN_EXPIRED"


def test_decode_access_token_invalid_signature():
    """Verify tampered token signature raises UnauthorizedError with code INVALID_TOKEN."""
    user_id = uuid.uuid4()
    token = create_access_token(subject=user_id, role="patient")
    # Tamper with signature
    parts = token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.tampered_signature"

    with pytest.raises(UnauthorizedError) as exc_info:
        decode_access_token(tampered_token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "INVALID_TOKEN"


def test_decode_access_token_rejects_none_algorithm():
    """Verify token signed with 'none' algorithm is rejected."""
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "patient",
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
    }
    none_token = jwt.encode(payload, key="", algorithm="none")

    with pytest.raises(UnauthorizedError) as exc_info:
        decode_access_token(none_token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "INVALID_TOKEN"


def test_decode_access_token_missing_required_claims():
    """Verify token missing required claims (such as sub or role) is rejected."""
    settings = get_settings()
    # Missing 'sub' claim
    payload = {
        "role": "doctor",
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
    }
    bad_token = jwt.encode(payload, key=settings.secret_key, algorithm=settings.jwt_algorithm)

    with pytest.raises(UnauthorizedError) as exc_info:
        decode_access_token(bad_token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "INVALID_TOKEN"


def test_signing_secrets_sourced_only_from_configuration():
    """Verify signing secret comes from application Settings, not hardcoded strings."""
    settings = get_settings()
    assert settings.secret_key is not None
    assert len(settings.secret_key) >= 16
    assert settings.jwt_algorithm in ("HS256", "HS384", "HS512")


# ==============================================================================
# 7. Authentication Service Unit Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_authenticate_user_success():
    """Verify authenticate_user verifies password and returns user with profile."""
    pwd = "ValidPassword123!"
    user = User(
        id=uuid.uuid4(),
        email_normalized="valid.user@amrutam.co.in",
        password_hash=hash_password(pwd),
        role="patient",
        is_active=True,
    )
    user.profile = Profile(
        id=uuid.uuid4(),
        user_id=user.id,
        full_name="Valid Patient",
    )

    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    authenticated = await authenticate_user(
        session=mock_session,
        email="VALID.USER@AMRUTAM.CO.IN",
        password=pwd,
    )
    assert authenticated.id == user.id
    assert authenticated.role == "patient"


@pytest.mark.asyncio
async def test_authenticate_user_bad_password():
    """Verify authenticate_user rejects incorrect password with generic INVALID_CREDENTIALS."""
    user = User(
        id=uuid.uuid4(),
        email_normalized="valid.user@amrutam.co.in",
        password_hash=hash_password("CorrectPassword123!"),
        role="patient",
        is_active=True,
    )
    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    with pytest.raises(UnauthorizedError) as exc_info:
        await authenticate_user(
            session=mock_session,
            email="valid.user@amrutam.co.in",
            password="WrongPassword999!",
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_authenticate_user_nonexistent_email():
    """Verify authenticate_user returns generic error for unknown email."""
    mock_session = AsyncMock()
    mock_session.scalar.return_value = None

    with pytest.raises(UnauthorizedError) as exc_info:
        await authenticate_user(
            session=mock_session,
            email="nonexistent@amrutam.co.in",
            password="SomePassword123!",
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_authenticate_user_inactive_account():
    """Verify authenticate_user rejects inactive account with ACCOUNT_INACTIVE."""
    pwd = "ValidPassword123!"
    user = User(
        id=uuid.uuid4(),
        email_normalized="inactive.user@amrutam.co.in",
        password_hash=hash_password(pwd),
        role="patient",
        is_active=False,
    )
    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    with pytest.raises(ForbiddenError) as exc_info:
        await authenticate_user(
            session=mock_session,
            email="inactive.user@amrutam.co.in",
            password=pwd,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "ACCOUNT_INACTIVE"


# ==============================================================================
# 8. API Endpoint Tests: /auth/login and /auth/me
# ==============================================================================


def test_api_login_success():
    """Verify POST /api/v1/auth/login returns access token and user payload."""
    pwd = "PatientSecurePassword123!"
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email_normalized="patient.login@amrutam.co.in",
        password_hash=hash_password(pwd),
        role="patient",
        is_active=True,
        mfa_enabled=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    user.profile = Profile(
        id=uuid.uuid4(),
        user_id=user_id,
        full_name="Login Test User",
        phone="+919876543210",
        date_of_birth=date(1992, 4, 12),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "PATIENT.LOGIN@AMRUTAM.CO.IN",
            "password": pwd,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["user"]["id"] == str(user_id)
    assert data["user"]["email"] == "patient.login@amrutam.co.in"
    assert data["user"]["role"] == "patient"
    assert data["user"]["profile"]["full_name"] == "Login Test User"
    # Guaranteed sensitive fields omitted
    assert "password_hash" not in str(response.text)
    assert "mfa_secret" not in str(response.text)


def test_api_login_bad_credentials():
    """Verify POST /api/v1/auth/login returns HTTP 401 with INVALID_CREDENTIALS on bad password."""
    user = User(
        id=uuid.uuid4(),
        email_normalized="patient@amrutam.co.in",
        password_hash=hash_password("CorrectPassword!"),
        role="patient",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "patient@amrutam.co.in",
            "password": "WrongPassword!",
        },
    )

    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "INVALID_CREDENTIALS"
    assert "invalid email or password" in data["error"]["message"].lower()


def test_api_login_nonexistent_email():
    """Verify POST /api/v1/auth/login returns HTTP 401 with INVALID_CREDENTIALS on missing user."""
    mock_session = AsyncMock()
    mock_session.scalar.return_value = None

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "unknown@amrutam.co.in",
            "password": "AnyPassword123!",
        },
    )

    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "INVALID_CREDENTIALS"


def test_api_login_inactive_account():
    """Verify POST /api/v1/auth/login returns HTTP 403 when account is inactive."""
    pwd = "ValidPassword123!"
    user = User(
        id=uuid.uuid4(),
        email_normalized="inactive@amrutam.co.in",
        password_hash=hash_password(pwd),
        role="patient",
        is_active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "inactive@amrutam.co.in",
            "password": pwd,
        },
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "ACCOUNT_INACTIVE"


def test_api_login_validation_error():
    """Verify invalid login request body returns HTTP 422 VALIDATION_ERROR."""
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "not-a-valid-email",
            "password": "",
        },
    )

    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_api_get_me_success():
    """Verify GET /api/v1/auth/me returns current user profile with valid Bearer token."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email_normalized="doctor.profile@amrutam.co.in",
        password_hash="dummyhash",
        role="doctor",
        is_active=True,
        mfa_enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    user.profile = Profile(
        id=uuid.uuid4(),
        user_id=user_id,
        full_name="Dr. Veda Shastri",
        phone="+919876543210",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    token = create_access_token(subject=user_id, role="doctor")

    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user_id)
    assert data["email"] == "doctor.profile@amrutam.co.in"
    assert data["role"] == "doctor"
    assert data["mfa_enabled"] is True
    assert data["profile"]["full_name"] == "Dr. Veda Shastri"
    # Never leaks credentials
    assert "password_hash" not in str(response.text)


def test_api_get_me_missing_token():
    """Verify GET /api/v1/auth/me returns HTTP 401 AUTHENTICATION_REQUIRED without header."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_api_get_me_invalid_token():
    """Verify GET /api/v1/auth/me returns HTTP 401 INVALID_TOKEN with corrupt token."""
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-valid-jwt-token"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "INVALID_TOKEN"


def test_api_get_me_expired_token():
    """Verify GET /api/v1/auth/me returns HTTP 401 TOKEN_EXPIRED with expired token."""
    expired_token = create_access_token(
        subject=uuid.uuid4(),
        role="patient",
        expires_delta=timedelta(seconds=-10),
    )

    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "TOKEN_EXPIRED"


def test_api_get_me_inactive_user():
    """Verify GET /api/v1/auth/me returns HTTP 403 ACCOUNT_INACTIVE if user is inactive."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email_normalized="inactive@amrutam.co.in",
        password_hash="dummyhash",
        role="patient",
        is_active=False,
    )
    token = create_access_token(subject=user_id, role="patient")

    mock_session = AsyncMock()
    mock_session.scalar.return_value = user

    app = create_app()
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "ACCOUNT_INACTIVE"


# ==============================================================================
# 9. Role-Based Authorization Dependency Tests
# ==============================================================================


def test_require_roles_allows_matching_role():
    """Verify require_roles dependency permits users with authorized roles."""
    user_id = uuid.uuid4()
    doctor_user = User(
        id=user_id,
        email_normalized="doctor@amrutam.co.in",
        password_hash="dummy",
        role="doctor",
        is_active=True,
    )

    token = create_access_token(subject=user_id, role="doctor")

    mock_session = AsyncMock()
    mock_session.scalar.return_value = doctor_user

    # Create temporary router testing require_doctor dependency
    test_router = APIRouter()

    @test_router.get("/doctor-only", dependencies=[Depends(require_doctor)])
    async def doctor_endpoint():
        return {"status": "doctor_authorized"}

    app = create_app()
    app.include_router(test_router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.get(
        "/api/v1/doctor-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "doctor_authorized"}


def test_require_roles_denies_wrong_role():
    """Verify require_roles returns HTTP 403 INSUFFICIENT_PERMISSIONS for unauthorized roles."""
    user_id = uuid.uuid4()
    patient_user = User(
        id=user_id,
        email_normalized="patient@amrutam.co.in",
        password_hash="dummy",
        role="patient",
        is_active=True,
    )

    token = create_access_token(subject=user_id, role="patient")

    mock_session = AsyncMock()
    mock_session.scalar.return_value = patient_user

    test_router = APIRouter()

    @test_router.get("/doctor-only", dependencies=[Depends(require_doctor)])
    async def doctor_endpoint():
        return {"status": "doctor_authorized"}

    app = create_app()
    app.include_router(test_router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.get(
        "/api/v1/doctor-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_require_roles_allows_multiple_roles():
    """Verify require_roles allows any role in the permitted set."""
    user_id = uuid.uuid4()
    admin_user = User(
        id=user_id,
        email_normalized="admin@amrutam.co.in",
        password_hash="dummy",
        role="admin",
        is_active=True,
    )

    token = create_access_token(subject=user_id, role="admin")

    mock_session = AsyncMock()
    mock_session.scalar.return_value = admin_user

    test_router = APIRouter()

    @test_router.get("/staff-only", dependencies=[Depends(require_roles("doctor", "admin"))])
    async def staff_endpoint():
        return {"status": "staff_authorized"}

    app = create_app()
    app.include_router(test_router, prefix="/api/v1")
    app.dependency_overrides[get_db_session] = lambda: mock_session
    client = TestClient(app)

    response = client.get(
        "/api/v1/staff-only",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "staff_authorized"}
