"""Tests for doctor public profile retrieval, searchable listing, and sensitive field redaction."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.errors import NotFoundError
from app.db.session import get_db_session
from app.main import create_app
from app.models.doctor import Doctor
from app.models.user import Profile, User
from app.schemas.doctor import DoctorListResponse, DoctorPublicResponse
from app.services.doctor_service import get_doctor_by_id, list_doctors
from fastapi.testclient import TestClient

from tests.conftest import is_postgres_available


def _create_mock_doctor(
    doctor_id: uuid.UUID | None = None,
    name: str = "Dr. Aarav Sharma",
    specialization: str = "Ayurveda",
    license_number: str = "LIC-987654",
    is_verified: bool = True,
    fee_minor: int = 50000,
    created_at: datetime | None = None,
) -> Doctor:
    """Helper to create a Doctor instance with linked User and Profile for testing."""
    doc_id = doctor_id or uuid.uuid4()
    u_id = uuid.uuid4()
    created = created_at or datetime.now(UTC)

    profile = Profile(
        id=uuid.uuid4(),
        user_id=u_id,
        full_name=name,
        phone="+919876543210",
        created_at=created,
        updated_at=created,
    )
    user = User(
        id=u_id,
        email_normalized="aarav.doctor@amrutam.co.in",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$dummyhash",
        role="doctor",
        is_active=True,
        mfa_enabled=True,
        mfa_secret_encrypted="mfa_secret_encrypted_data",
        created_at=created,
        updated_at=created,
    )
    user.profile = profile

    doc = Doctor(
        id=doc_id,
        user_id=u_id,
        specialization=specialization,
        license_number=license_number,
        is_verified=is_verified,
        consultation_fee_minor=fee_minor,
        currency="INR",
        bio="Experienced Ayurvedic physician specializing in holistic health.",
        created_at=created,
        updated_at=created,
    )
    doc.user = user
    return doc


def _build_mock_session() -> AsyncMock:
    """Create a configured AsyncMock session with synchronous methods properly stubbed."""
    session = AsyncMock()
    session.add = MagicMock()
    session.in_transaction = MagicMock(return_value=True)
    return session


# ==============================================================================
# 1. Schema Invariants and Redaction Unit Tests
# ==============================================================================


def test_doctor_public_response_redacts_license_and_credentials():
    """Verify DoctorPublicResponse strictly omits license_number, passwords, and private data."""
    doctor = _create_mock_doctor()
    resp = DoctorPublicResponse.model_validate(doctor)
    data = resp.model_dump(mode="json")

    # Public fields must be present
    assert data["id"] == str(doctor.id)
    assert data["name"] == "Dr. Aarav Sharma"
    assert data["specialization"] == "Ayurveda"
    assert data["is_verified"] is True
    assert data["consultation_fee_minor"] == 50000
    assert data["currency"] == "INR"
    assert "holistic health" in data["bio"]
    assert "created_at" in data
    assert "updated_at" in data

    # Strictly confidential and internal fields MUST NOT exist in schema
    assert "license_number" not in data
    assert "license" not in data
    assert "password_hash" not in data
    assert "password" not in data
    assert "email_normalized" not in data
    assert "email" not in data
    assert "mfa_secret_encrypted" not in data
    assert "phone" not in data
    assert "date_of_birth" not in data


def test_doctor_list_response_schema():
    """Verify DoctorListResponse pagination metadata formatting."""
    doctor = _create_mock_doctor()
    public_doc = DoctorPublicResponse.model_validate(doctor)

    list_resp = DoctorListResponse(
        items=[public_doc],
        total=1,
        page=1,
        page_size=20,
        total_pages=1,
    )
    dumped = list_resp.model_dump(mode="json")
    assert dumped["total"] == 1
    assert dumped["page"] == 1
    assert dumped["page_size"] == 20
    assert dumped["total_pages"] == 1
    assert len(dumped["items"]) == 1


# ==============================================================================
# 2. Service Layer Unit Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_get_doctor_by_id_service_found():
    """Verify get_doctor_by_id returns the matching doctor when present."""
    doctor = _create_mock_doctor()
    session = _build_mock_session()
    session.scalar.return_value = doctor

    result = await get_doctor_by_id(session, doctor.id)
    assert result.id == doctor.id
    assert result.name == "Dr. Aarav Sharma"
    assert result.specialization == "Ayurveda"


@pytest.mark.asyncio
async def test_get_doctor_by_id_service_not_found_raises_404():
    """Verify get_doctor_by_id raises NotFoundError when doctor does not exist."""
    session = _build_mock_session()
    session.scalar.return_value = None

    non_existent_id = uuid.uuid4()
    with pytest.raises(NotFoundError) as exc_info:
        await get_doctor_by_id(session, non_existent_id)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "DOCTOR_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_doctors_service_pagination_and_sorting():
    """Verify list_doctors calculates total pages and applies deterministic sorting."""
    now = datetime.now(UTC)
    doc1 = _create_mock_doctor(
        name="Doc One",
        created_at=now - timedelta(minutes=10),
    )
    doc2 = _create_mock_doctor(
        name="Doc Two",
        created_at=now,
    )

    session = _build_mock_session()
    # Total count = 2
    session.scalar.return_value = 2

    # Return doc2 then doc1 (created_at DESC)
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [doc2, doc1]
    session.scalars.return_value = mock_scalars

    items, total, total_pages = await list_doctors(session, page=1, page_size=10)

    assert total == 2
    assert total_pages == 1
    assert len(items) == 2
    assert items[0].name == "Doc Two"
    assert items[1].name == "Doc One"


# ==============================================================================
# 3. API Endpoint Integration Tests (TestClient)
# ==============================================================================


def test_api_list_doctors_default_pagination():
    """Verify GET /api/v1/doctors returns 200 with default pagination metadata."""
    app = create_app()
    doc = _create_mock_doctor()

    async def mock_get_db_session():
        session = _build_mock_session()
        session.scalar.return_value = 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [doc]
        session.scalars.return_value = mock_scalars
        yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    client = TestClient(app)
    response = client.get("/api/v1/doctors")

    assert response.status_code == 200
    data = response.json()

    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["total"] == 1
    assert data["total_pages"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Dr. Aarav Sharma"
    assert data["items"][0]["specialization"] == "Ayurveda"


def test_api_list_doctors_filtering_queries():
    """Verify filtering parameters (specialization, is_verified, search, name) pass to service."""
    app = create_app()
    doc = _create_mock_doctor(specialization="Panchakarma", is_verified=True)

    async def mock_get_db_session():
        session = _build_mock_session()
        session.scalar.return_value = 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [doc]
        session.scalars.return_value = mock_scalars
        yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    client = TestClient(app)
    # Query with multiple filters
    response = client.get(
        "/api/v1/doctors?specialization=Panchakarma&is_verified=true&name=Aarav&search=holistic"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["specialization"] == "Panchakarma"
    assert data["items"][0]["is_verified"] is True


def test_api_list_doctors_pagination_bounds_validation():
    """Verify bounds enforcement: page_size > 100 or < 1, and page < 1 return HTTP 422."""
    app = create_app()
    client = TestClient(app)

    # 1. page_size exceeds max (100)
    resp1 = client.get("/api/v1/doctors?page_size=101")
    assert resp1.status_code == 422
    data1 = resp1.json()
    assert data1["error"]["code"] == "VALIDATION_ERROR"

    # 2. page_size below min (1)
    resp2 = client.get("/api/v1/doctors?page_size=0")
    assert resp2.status_code == 422
    data2 = resp2.json()
    assert data2["error"]["code"] == "VALIDATION_ERROR"

    # 3. page below min (1)
    resp3 = client.get("/api/v1/doctors?page=0")
    assert resp3.status_code == 422
    data3 = resp3.json()
    assert data3["error"]["code"] == "VALIDATION_ERROR"


def test_api_list_doctors_strict_redaction():
    """Verify response payload never leaks license_number, credentials, or personal contact info."""
    app = create_app()
    doc = _create_mock_doctor(license_number="CONFIDENTIAL_LICENSE_XYZ_999")

    async def mock_get_db_session():
        session = _build_mock_session()
        session.scalar.return_value = 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [doc]
        session.scalars.return_value = mock_scalars
        yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    client = TestClient(app)
    response = client.get("/api/v1/doctors")

    assert response.status_code == 200
    raw_text = response.text

    assert "CONFIDENTIAL_LICENSE_XYZ_999" not in raw_text
    assert "license_number" not in raw_text
    assert "password" not in raw_text
    assert "mfa_secret" not in raw_text
    assert "aarav.doctor@amrutam.co.in" not in raw_text
    assert "+919876543210" not in raw_text


def test_api_get_doctor_by_id_success():
    """Verify GET /api/v1/doctors/{id} returns 200 with public profile details."""
    app = create_app()
    doc = _create_mock_doctor()

    async def mock_get_db_session():
        session = _build_mock_session()
        session.scalar.return_value = doc
        yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    client = TestClient(app)
    response = client.get(f"/api/v1/doctors/{doc.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(doc.id)
    assert data["name"] == "Dr. Aarav Sharma"
    assert data["specialization"] == "Ayurveda"
    assert data["consultation_fee_minor"] == 50000
    assert data["currency"] == "INR"

    # Redaction checks
    raw = response.text
    assert "license_number" not in raw
    assert "password" not in raw
    assert "email" not in raw


def test_api_get_doctor_by_id_not_found():
    """Verify GET /api/v1/doctors/{id} returns 404 with standardized error envelope."""
    app = create_app()

    async def mock_get_db_session():
        session = _build_mock_session()
        session.scalar.return_value = None
        yield session

    app.dependency_overrides[get_db_session] = mock_get_db_session

    client = TestClient(app)
    missing_id = uuid.uuid4()
    response = client.get(f"/api/v1/doctors/{missing_id}")

    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "DOCTOR_NOT_FOUND"
    assert "not found" in data["error"]["message"].lower()
    assert data["error"]["request_id"] is not None


# ==============================================================================
# 4. Live PostgreSQL Integration Tests (Skipped when DB is unreachable)
# ==============================================================================


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
@pytest.mark.asyncio
async def test_live_postgres_doctor_querying_and_filtering():
    """Verify doctor persistence, relationships, and queries against live PostgreSQL."""
    unique_suffix = uuid.uuid4().hex[:8]
    doc_license = f"LIC-TEST-{unique_suffix}"
    email = f"doc_{unique_suffix}@example.com"

    async for session in get_db_session():
        # Create user
        user = User(
            email_normalized=email,
            password_hash="argon2_hashed_placeholder",
            role="doctor",
        )
        session.add(user)
        await session.flush()

        # Create profile
        profile = Profile(
            user_id=user.id,
            full_name=f"Dr. Test {unique_suffix}",
        )
        session.add(profile)

        # Create doctor
        doctor = Doctor(
            user_id=user.id,
            specialization="Ayurveda",
            license_number=doc_license,
            is_verified=True,
            consultation_fee_minor=75000,
            currency="INR",
            bio="Holistic healthcare practitioner",
        )
        session.add(doctor)
        await session.commit()

        # Verify retrieval via list_doctors
        results, total, _ = await list_doctors(
            session,
            specialization="Ayurveda",
            name=f"Dr. Test {unique_suffix}",
            is_verified=True,
        )
        assert total >= 1
        assert any(d.id == doctor.id for d in results)

        # Verify retrieval via get_doctor_by_id
        fetched = await get_doctor_by_id(session, doctor.id)
        assert fetched.id == doctor.id
        assert fetched.name == f"Dr. Test {unique_suffix}"
        break
