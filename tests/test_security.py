"""Security, authorization, IDOR prevention, and data redaction tests (Layer 4)."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from app.core.security import create_access_token, hash_password
from app.db.session import get_db_session
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.payment import Payment
from app.models.user import Profile, User
from app.services.audit_service import sanitize_audit_metadata
from app.services.payment_provider import MockPaymentProviderAdapter
from fastapi.testclient import TestClient

pytestmark = pytest.mark.security


def _build_mock_session() -> AsyncMock:
    """Create a configured AsyncMock session with transaction stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.in_transaction = MagicMock(return_value=True)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock()
    cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=cm)
    return session


def _create_user(
    *,
    user_id: uuid.UUID | None = None,
    role: str = "patient",
    is_active: bool = True,
    email: str | None = None,
    full_name: str = "Test User",
) -> User:
    uid = user_id or uuid.uuid4()
    u = User(
        id=uid,
        email_normalized=email or f"{role}_{uid.hex[:6]}@example.com",
        password_hash=hash_password("SuperSecretPass123!"),
        role=role,
        is_active=is_active,
        mfa_enabled=False,
        mfa_secret_encrypted="encrypted_mfa_secret_test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    p = Profile(
        id=uuid.uuid4(),
        user_id=uid,
        full_name=full_name,
        date_of_birth=date(1990, 1, 1),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    u.profile = p
    return u


def _create_doctor(user: User, doctor_id: uuid.UUID | None = None) -> Doctor:
    doc_id = doctor_id or uuid.uuid4()
    doc = Doctor(
        id=doc_id,
        user_id=user.id,
        specialization="Ayurveda",
        license_number=f"DOC-{doc_id.hex[:6].upper()}",
        is_verified=True,
        consultation_fee_minor=1500,
        currency="INR",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    doc.user = user
    user.doctor = doc
    return doc


def _create_consultation(
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    *,
    status: str = "booked",
    consultation_id: uuid.UUID | None = None,
) -> Consultation:
    cid = consultation_id or uuid.uuid4()
    return Consultation(
        id=cid,
        patient_id=patient_id,
        doctor_id=doctor_id,
        slot_id=uuid.uuid4(),
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ==============================================================================
# 1. IDOR & Cross-Tenant Resource Isolation Tests
# ==============================================================================


def test_idor_patient_cannot_view_other_patient_consultation(client: TestClient) -> None:
    """Verify Patient A cannot view Patient B's consultation by guessing UUID (HTTP 403)."""
    patient_a = _create_user(role="patient", full_name="Patient A")
    patient_b = _create_user(role="patient", full_name="Patient B")
    doctor_user = _create_user(role="doctor", full_name="Dr. Ayurvedic")
    doctor = _create_doctor(doctor_user)

    consultation_b = _create_consultation(patient_b.id, doctor.id, status="confirmed")

    token_a = create_access_token(subject=patient_a.id, role="patient")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str or "users.id" in stmt_str:
            return patient_a
        if "from consultations" in stmt_str or "consultations.id" in stmt_str:
            return consultation_b
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.get(
        f"/api/v1/consultations/{consultation_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "CONSULTATION_ACCESS_FORBIDDEN"


def test_idor_patient_cannot_cancel_other_patient_booking(client: TestClient) -> None:
    """Verify Patient A cannot cancel Patient B's booking (HTTP 403)."""
    patient_a = _create_user(role="patient", full_name="Patient A")
    patient_b = _create_user(role="patient", full_name="Patient B")
    doctor_user = _create_user(role="doctor", full_name="Dr. Ayurvedic")
    doctor = _create_doctor(doctor_user)

    booking_b = _create_consultation(patient_b.id, doctor.id, status="booked")

    token_a = create_access_token(subject=patient_a.id, role="patient")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return patient_a
        if "from idempotency_records" in stmt_str:
            return None
        if "from consultations" in stmt_str:
            return booking_b
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.post(
        f"/api/v1/bookings/{booking_b.id}/cancel",
        headers={
            "Authorization": f"Bearer {token_a}",
            "Idempotency-Key": f"cancel-idor-{uuid.uuid4().hex[:8]}",
        },
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "BOOKING_ACCESS_FORBIDDEN"


def test_idor_unassigned_doctor_cannot_view_consultation(client: TestClient) -> None:
    """Verify Doctor A cannot view consultations assigned to Doctor B (HTTP 403)."""
    patient = _create_user(role="patient", full_name="Patient Target")
    doc_a_user = _create_user(role="doctor", full_name="Dr. Unassigned")
    doc_a = _create_doctor(doc_a_user)

    doc_b_user = _create_user(role="doctor", full_name="Dr. Assigned")
    doc_b = _create_doctor(doc_b_user)

    consultation = _create_consultation(patient.id, doc_b.id, status="in_progress")

    token_doc_a = create_access_token(subject=doc_a_user.id, role="doctor")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return doc_a_user
        if "from consultations" in stmt_str:
            return consultation
        if "from doctors" in stmt_str:
            return doc_a.id
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.get(
        f"/api/v1/consultations/{consultation.id}",
        headers={"Authorization": f"Bearer {token_doc_a}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "CONSULTATION_ACCESS_FORBIDDEN"


def test_idor_unassigned_doctor_cannot_transition_consultation(client: TestClient) -> None:
    """Verify Doctor A cannot transition state of Doctor B's consultation (HTTP 403)."""
    patient = _create_user(role="patient", full_name="Patient Target")
    doc_a_user = _create_user(role="doctor", full_name="Dr. Intruder")
    doc_a = _create_doctor(doc_a_user)

    doc_b_user = _create_user(role="doctor", full_name="Dr. Legitimate")
    doc_b = _create_doctor(doc_b_user)

    consultation = _create_consultation(patient.id, doc_b.id, status="confirmed")

    token_doc_a = create_access_token(subject=doc_a_user.id, role="doctor")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return doc_a_user
        if "from consultations" in stmt_str:
            return consultation
        if "from doctors" in stmt_str:
            return doc_a.id
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    # Doctor A attempts to start Doctor B's consultation
    response = client.post(
        f"/api/v1/consultations/{consultation.id}/start",
        headers={"Authorization": f"Bearer {token_doc_a}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "CONSULTATION_NOT_ASSIGNED_DOCTOR"


def test_idor_patient_cannot_view_other_patient_prescription(client: TestClient) -> None:
    """Verify Patient A cannot view Patient B's prescription (HTTP 403)."""
    patient_a = _create_user(role="patient", full_name="Patient A")
    patient_b = _create_user(role="patient", full_name="Patient B")
    doctor_user = _create_user(role="doctor", full_name="Dr. Legitimate")
    doctor = _create_doctor(doctor_user)

    consultation = _create_consultation(patient_b.id, doctor.id, status="completed")

    token_a = create_access_token(subject=patient_a.id, role="patient")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return patient_a
        if "from consultations" in stmt_str:
            return consultation
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.get(
        f"/api/v1/consultations/{consultation.id}/prescription",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "PRESCRIPTION_ACCESS_FORBIDDEN"


def test_idor_unassigned_doctor_cannot_issue_or_amend_prescription(client: TestClient) -> None:
    """Verify an unassigned doctor cannot issue or amend prescriptions for a consultation."""
    patient = _create_user(role="patient", full_name="Patient Target")
    doc_a_user = _create_user(role="doctor", full_name="Dr. Unassigned")
    doc_a = _create_doctor(doc_a_user)

    doc_b_user = _create_user(role="doctor", full_name="Dr. Assigned")
    doc_b = _create_doctor(doc_b_user)

    consultation = _create_consultation(patient.id, doc_b.id, status="in_progress")

    token_doc_a = create_access_token(subject=doc_a_user.id, role="doctor")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return doc_a_user
        if "from consultations" in stmt_str:
            return consultation
        if "from doctors" in stmt_str:
            return doc_a.id
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.post(
        f"/api/v1/consultations/{consultation.id}/prescriptions",
        headers={"Authorization": f"Bearer {token_doc_a}"},
        json={
            "notes": "Intruder prescription attempt",
            "items": [
                {
                    "medicine_name": "Triphala",
                    "dosage": "500mg",
                    "route": "oral",
                    "frequency": "daily",
                    "duration": "7 days",
                }
            ],
        },
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "PRESCRIPTION_NOT_ASSIGNED_DOCTOR"


def test_idor_patient_cannot_view_other_patient_payment(client: TestClient) -> None:
    """Verify Patient A cannot view Patient B's payment details (HTTP 403)."""
    patient_a = _create_user(role="patient", full_name="Patient A")
    patient_b = _create_user(role="patient", full_name="Patient B")
    doctor_user = _create_user(role="doctor", full_name="Dr. Healer")
    doctor = _create_doctor(doctor_user)

    consultation_b = _create_consultation(patient_b.id, doctor.id, status="confirmed")
    payment_b = Payment(
        id=uuid.uuid4(),
        consultation_id=consultation_b.id,
        amount_minor=1500,
        currency="INR",
        status="succeeded",
        provider="mock_provider",
        provider_reference="pay_ref_b",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payment_b.consultation = consultation_b

    token_a = create_access_token(subject=patient_a.id, role="patient")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return patient_a
        if "from payments" in stmt_str:
            return payment_b
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.get(
        f"/api/v1/payments/{payment_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "PAYMENT_ACCESS_FORBIDDEN"


def test_idor_patient_cannot_pay_for_other_patient_consultation(client: TestClient) -> None:
    """Verify Patient A cannot initiate payment for Patient B's consultation (HTTP 403)."""
    patient_a = _create_user(role="patient", full_name="Patient A")
    patient_b = _create_user(role="patient", full_name="Patient B")
    doctor_user = _create_user(role="doctor", full_name="Dr. Healer")
    doctor = _create_doctor(doctor_user)

    consultation_b = _create_consultation(patient_b.id, doctor.id, status="confirmed")

    token_a = create_access_token(subject=patient_a.id, role="patient")

    mock_session = _build_mock_session()

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from users" in stmt_str:
            return patient_a
        if "from idempotency_records" in stmt_str:
            return None
        if "from consultations" in stmt_str:
            return consultation_b
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.post(
        f"/api/v1/consultations/{consultation_b.id}/payments",
        headers={
            "Authorization": f"Bearer {token_a}",
            "Idempotency-Key": f"pay-idor-{uuid.uuid4().hex[:8]}",
        },
        json={},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "PAYMENT_FORBIDDEN"


# ==============================================================================
# 2. Role-Based Privilege Separation & Boundary Tests
# ==============================================================================


def test_rbac_patient_cannot_manage_doctor_availability(client: TestClient) -> None:
    """Verify patient role receives HTTP 403 when attempting doctor availability writes."""
    patient = _create_user(role="patient")
    token = create_access_token(subject=patient.id, role="patient")

    mock_session = _build_mock_session()
    mock_session.scalar.return_value = patient

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    now = datetime.now(UTC) + timedelta(days=2)
    response = client.post(
        "/api/v1/doctors/me/slots",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "slots": [
                {
                    "start_at": now.isoformat(),
                    "end_at": (now + timedelta(minutes=30)).isoformat(),
                }
            ]
        },
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_rbac_patient_cannot_issue_prescriptions(client: TestClient) -> None:
    """Verify patient role receives HTTP 403 attempting prescription endpoints."""
    patient = _create_user(role="patient")
    token = create_access_token(subject=patient.id, role="patient")

    mock_session = _build_mock_session()
    mock_session.scalar.return_value = patient

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.post(
        f"/api/v1/consultations/{uuid.uuid4()}/prescriptions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "notes": "Prescription attempt by patient",
            "items": [
                {
                    "medicine_name": "Ashwagandha",
                    "dosage": "500mg",
                    "route": "oral",
                    "frequency": "daily",
                    "duration": "5 days",
                }
            ],
        },
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_rbac_doctor_cannot_create_patient_booking(client: TestClient) -> None:
    """Verify doctor role cannot call patient-only booking creation endpoint (HTTP 403)."""
    doctor_user = _create_user(role="doctor")
    token = create_access_token(subject=doctor_user.id, role="doctor")

    mock_session = _build_mock_session()
    mock_session.scalar.return_value = doctor_user

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.post(
        "/api/v1/bookings",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"doc-book-{uuid.uuid4().hex[:8]}",
        },
        json={"doctor_id": str(uuid.uuid4()), "slot_id": str(uuid.uuid4())},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_rbac_non_admin_cannot_access_audit_logs(client: TestClient) -> None:
    """Verify both patient and doctor roles cannot access admin audit logs (HTTP 403)."""
    patient = _create_user(role="patient")
    doctor_user = _create_user(role="doctor")

    token_patient = create_access_token(subject=patient.id, role="patient")
    token_doctor = create_access_token(subject=doctor_user.id, role="doctor")

    mock_session = _build_mock_session()

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    # 1. Test Patient
    mock_session.scalar.return_value = patient
    resp_patient = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {token_patient}"},
    )
    assert resp_patient.status_code == 403
    assert resp_patient.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # 2. Test Doctor
    mock_session.scalar.return_value = doctor_user
    resp_doctor = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {token_doctor}"},
    )
    assert resp_doctor.status_code == 403
    assert resp_doctor.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


def test_rbac_non_admin_cannot_access_analytics_consultations(client: TestClient) -> None:
    """Verify both patient and doctor roles cannot access admin analytics (HTTP 403)."""
    patient = _create_user(role="patient")
    doctor_user = _create_user(role="doctor")

    token_patient = create_access_token(subject=patient.id, role="patient")
    token_doctor = create_access_token(subject=doctor_user.id, role="doctor")

    mock_session = _build_mock_session()

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    # 1. Patient check
    mock_session.scalar.return_value = patient
    res_p = client.get(
        "/api/v1/admin/analytics/consultations",
        headers={"Authorization": f"Bearer {token_patient}"},
    )
    assert res_p.status_code == 403
    assert res_p.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # 2. Doctor check
    mock_session.scalar.return_value = doctor_user
    res_d = client.get(
        "/api/v1/admin/analytics/consultations",
        headers={"Authorization": f"Bearer {token_doctor}"},
    )
    assert res_d.status_code == 403
    assert res_d.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"


# ==============================================================================
# 3. Authentication & JWT Token Security Boundaries
# ==============================================================================


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/consultations"),
        ("POST", "/api/v1/bookings"),
        ("POST", "/api/v1/doctors/me/slots"),
        ("GET", "/api/v1/admin/audit-logs"),
        ("GET", "/api/v1/admin/analytics/consultations"),
    ],
)
def test_unauthenticated_request_rejected_on_protected_endpoints(
    client: TestClient, method: str, path: str
) -> None:
    """Verify missing Authorization header produces HTTP 401 AUTHENTICATION_REQUIRED."""
    response = client.request(method, path)
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.parametrize(
    "invalid_header",
    [
        "Basic dXNlcjpwYXNz",
        "Token some_random_opaque_token",
        "Bearer",
        "Bearer  ",
        "NotBearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abc",
    ],
)
def test_malformed_authorization_headers_rejected(client: TestClient, invalid_header: str) -> None:
    """Verify non-Bearer or malformed authorization headers return HTTP 401."""
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": invalid_header},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] in ("AUTHENTICATION_REQUIRED", "INVALID_TOKEN")


def test_tampered_jwt_signature_rejected(client: TestClient) -> None:
    """Verify altered JWT signature is strictly rejected with HTTP 401 INVALID_TOKEN."""
    user = _create_user()
    valid_token = create_access_token(subject=user.id, role="patient")
    parts = valid_token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.tampered_signature_payload"

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_jwt_token_rejected(client: TestClient) -> None:
    """Verify expired token returns HTTP 401 TOKEN_EXPIRED."""
    user = _create_user()
    expired_token = create_access_token(
        subject=user.id,
        role="patient",
        expires_delta=timedelta(seconds=-30),
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_jwt_none_algorithm_rejected(client: TestClient) -> None:
    """Verify algorithm 'none' token injection attack is strictly rejected."""
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "admin",
        "iat": int(datetime.now(UTC).timestamp()),
        "nbf": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    none_token = jwt.encode(payload, key="", algorithm="none")

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {none_token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_jwt_wrong_secret_key_rejected(client: TestClient) -> None:
    """Verify tokens signed with a different secret key are rejected."""
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "patient",
        "iat": int(datetime.now(UTC).timestamp()),
        "nbf": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    bogus_token = jwt.encode(payload, key="untrusted-impostor-secret-key-32b!", algorithm="HS256")

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bogus_token}"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_inactive_user_token_rejected_with_account_inactive(client: TestClient) -> None:
    """Verify deactivated user account cannot make requests even with valid token (HTTP 403)."""
    inactive_user = _create_user(is_active=False)
    token = create_access_token(subject=inactive_user.id, role="patient")

    mock_session = _build_mock_session()
    mock_session.scalar.return_value = inactive_user

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


# ==============================================================================
# 4. Data Leakage, Secrets Redaction & Error Masking Tests
# ==============================================================================


def test_api_responses_never_leak_credentials(client: TestClient) -> None:
    """Verify password_hash and mfa_secret are absent from responses across auth endpoints."""
    raw_pwd = "MySuperSecretPassword2026!"
    hashed = hash_password(raw_pwd)

    user = _create_user(email="patient.leak@example.com")
    user.password_hash = hashed
    user.mfa_enabled = True
    user.mfa_secret_encrypted = "encrypted_secret_vault_abc"

    token = create_access_token(subject=user.id, role="patient")

    mock_session = _build_mock_session()
    mock_session.scalar.return_value = user

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    # 1. Check /api/v1/auth/me
    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    text = me_resp.text
    assert "password_hash" not in text
    assert hashed not in text
    assert "encrypted_secret_vault_abc" not in text
    assert "mfa_secret" not in text

    # 2. Check /api/v1/auth/login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "patient.leak@example.com", "password": raw_pwd},
    )
    assert login_resp.status_code == 200
    login_text = login_resp.text
    assert "password_hash" not in login_text
    assert hashed not in login_text
    assert "encrypted_secret_vault_abc" not in login_text
    assert raw_pwd not in login_text


def test_audit_metadata_sanitizer_redacts_all_phi_and_secrets() -> None:
    """Verify sanitize_audit_metadata strips passwords, tokens, MFA secrets, and PHI notes."""
    payload = {
        "password": "attempted_leak_pwd",
        "token": "bearer eyJhbGci...",
        "mfa_secret": "TOPSECRETMFATOKEN",
        "card_number": "4111222233334444",
        "cvv": "999",
        "prescription_items": [{"med": "sensitive"}],
        "notes": "Sensitive psychiatric evaluation notes",
        "diagnosis": "Sensitive medical diagnosis",
        # Non-sensitive allowed metadata
        "doctor_id": str(uuid.uuid4()),
        "status": "confirmed",
    }

    sanitized = sanitize_audit_metadata(payload)
    assert sanitized is not None

    for forbidden in [
        "password",
        "token",
        "mfa_secret",
        "card_number",
        "cvv",
        "prescription_items",
        "notes",
        "diagnosis",
    ]:
        assert forbidden not in sanitized

    assert "doctor_id" in sanitized
    assert sanitized["status"] == "confirmed"


# ==============================================================================
# 5. Payment Webhook HMAC Signature Security Tests
# ==============================================================================


def test_payment_webhook_missing_signature_rejected(client: TestClient) -> None:
    """Verify webhook without signature header is rejected with HTTP 401."""
    body = {
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "event_type": "payment.succeeded",
        "provider_reference": "pay_ref_123",
    }

    response = client.post(
        "/api/v1/payments/webhooks/mock_provider",
        json=body,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


def test_payment_webhook_tampered_signature_rejected(client: TestClient) -> None:
    """Verify webhook with invalid HMAC signature is rejected with HTTP 401."""
    body = {
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "event_type": "payment.succeeded",
        "provider_reference": "pay_ref_123",
    }

    response = client.post(
        "/api/v1/payments/webhooks/mock_provider",
        headers={"X-Webhook-Signature": "sha256=invalid_tampered_signature_hash"},
        json=body,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"


def test_payment_webhook_valid_signature_accepted(client: TestClient) -> None:
    """Verify webhook with valid HMAC SHA256 signature is processed successfully."""
    payload_obj = {
        "event_id": f"evt_valid_{uuid.uuid4().hex[:8]}",
        "event_type": "payment.succeeded",
        "provider_reference": "pay_ref_valid",
    }
    raw_body = json.dumps(payload_obj).encode("utf-8")
    valid_sig = MockPaymentProviderAdapter.generate_signature(
        raw_body, MockPaymentProviderAdapter.DEFAULT_SECRET
    )

    mock_session = _build_mock_session()

    consultation = _create_consultation(uuid.uuid4(), uuid.uuid4())
    payment = Payment(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        amount_minor=1500,
        currency="INR",
        status="pending",
        provider="mock_provider",
        provider_reference="pay_ref_valid",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def mock_scalar_impl(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "from payments" in stmt_str:
            return payment
        return None

    mock_session.scalar.side_effect = mock_scalar_impl

    app = client.app
    app.dependency_overrides[get_db_session] = lambda: mock_session

    response = client.post(
        "/api/v1/payments/webhooks/mock_provider",
        headers={
            "X-Webhook-Signature": valid_sig,
            "Content-Type": "application/json",
        },
        content=raw_body,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["payment_status"] == "succeeded"
