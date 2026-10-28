"""Automated tests for payment lifecycle, mock provider adapter, idempotency, and webhooks."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.deps import require_patient
from app.core.errors import ConflictError, ForbiddenError
from app.db.session import get_session_factory
from app.main import create_app
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.outbox import OutboxEvent
from app.models.payment import Payment
from app.models.user import User
from app.schemas.payment import PaymentCreateRequest, WebhookEventPayload
from app.services.payment_provider import MockPaymentProviderAdapter
from app.services.payment_service import (
    get_payment_by_id,
    initiate_consultation_payment,
    process_provider_webhook,
)
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from tests.conftest import is_postgres_available


def _async_context_manager() -> MagicMock:
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock()
    context_manager.__aexit__ = AsyncMock(return_value=False)
    return context_manager


def _make_mock_session(added_list: list[object] | None = None) -> AsyncMock:
    session = AsyncMock()
    session.begin_nested = MagicMock(return_value=_async_context_manager())
    if added_list is not None:
        session.add = MagicMock(side_effect=added_list.append)
    else:
        session.add = MagicMock()
    idemp_rec = MagicMock()
    idemp_rec.status = "in_progress"
    session.get.return_value = idemp_rec
    return session


def _make_user(*, role: str = "patient") -> User:
    return User(
        id=uuid.uuid4(),
        email_normalized=f"{role}_{uuid.uuid4().hex[:6]}@example.com",
        password_hash="placeholder_hash",
        role=role,
        is_active=True,
    )


def _make_consultation(
    *,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    status: str = "confirmed",
) -> Consultation:
    now = datetime.now(UTC)
    return Consultation(
        id=uuid.uuid4(),
        patient_id=patient_id,
        doctor_id=doctor_id,
        slot_id=uuid.uuid4(),
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_doctor(user_id: uuid.UUID, fee: int = 1500) -> Doctor:
    now = datetime.now(UTC)
    return Doctor(
        id=uuid.uuid4(),
        user_id=user_id,
        specialization="Ayurveda General",
        license_number=f"DOC-{uuid.uuid4().hex[:8].upper()}",
        is_verified=True,
        consultation_fee_minor=fee,
        currency="INR",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Unit / Service Level Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initiate_payment_success() -> None:
    """Happy path: patient initiates payment, receives succeeded response, and events recorded."""
    patient = _make_user(role="patient")
    doctor_user = _make_user(role="doctor")
    doctor = _make_doctor(doctor_user.id, fee=1200)
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=doctor.id, status="confirmed"
    )

    added_items: list[object] = []
    session = _make_mock_session(added_items)

    # First scalar: IdempotencyRecord (None)
    # Second scalar: Consultation
    # Third scalar: existing Payment (None)
    # Fourth scalar: Doctor
    session.scalar.side_effect = [None, consultation, None, doctor]

    result = await initiate_consultation_payment(
        session=session,
        consultation_id=consultation.id,
        payload=PaymentCreateRequest(amount_minor=1200),
        current_user=patient,
        idempotency_key="ik_pay_test_01",
    )

    assert result.status == "succeeded"
    assert result.amount_minor == 1200
    assert result.currency == "INR"
    assert result.provider == "mock_provider"
    assert result.provider_reference.startswith("mock_pi_")

    # Verify Payment, AuditLog, and OutboxEvent were created
    payments = [x for x in added_items if isinstance(x, Payment)]
    assert len(payments) == 1
    assert payments[0].amount_minor == 1200

    outbox = [x for x in added_items if isinstance(x, OutboxEvent)]
    assert any(o.event_type == "payment.succeeded" for o in outbox)

    # Verify no sensitive card details or tokens exist in outbox payload
    for o in outbox:
        assert "pan" not in o.payload
        assert "cvv" not in o.payload
        assert "client_secret" not in o.payload


@pytest.mark.asyncio
async def test_initiate_payment_forbidden_for_other_patient() -> None:
    """Patient cannot initiate payment for another patient's consultation."""
    patient_1 = _make_user(role="patient")
    patient_2 = _make_user(role="patient")
    consultation = _make_consultation(
        patient_id=patient_1.id, doctor_id=uuid.uuid4(), status="confirmed"
    )

    session = _make_mock_session()
    session.scalar.side_effect = [None, consultation]

    with pytest.raises(ForbiddenError) as exc_info:
        await initiate_consultation_payment(
            session=session,
            consultation_id=consultation.id,
            payload=PaymentCreateRequest(),
            current_user=patient_2,
            idempotency_key="ik_pay_forbidden",
        )
    assert exc_info.value.code == "PAYMENT_FORBIDDEN"


@pytest.mark.asyncio
async def test_initiate_payment_ineligible_consultation_status() -> None:
    """Cannot pay for cancelled or no_show consultations."""
    patient = _make_user(role="patient")
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=uuid.uuid4(), status="cancelled"
    )

    session = _make_mock_session()
    session.scalar.side_effect = [None, consultation]

    with pytest.raises(ConflictError) as exc_info:
        await initiate_consultation_payment(
            session=session,
            consultation_id=consultation.id,
            payload=PaymentCreateRequest(),
            current_user=patient,
            idempotency_key="ik_pay_cancelled",
        )
    assert exc_info.value.code == "CONSULTATION_INELIGIBLE_FOR_PAYMENT"


@pytest.mark.asyncio
async def test_initiate_payment_already_paid() -> None:
    """Cannot pay if consultation already has a succeeded payment."""
    patient = _make_user(role="patient")
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=uuid.uuid4(), status="confirmed"
    )
    existing_payment = Payment(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        amount_minor=1000,
        currency="INR",
        status="succeeded",
        provider="mock_provider",
        provider_reference="mock_pi_existing",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    session = _make_mock_session()
    # 1. Idempotency (None), 2. Consultation, 3. existing Payment
    session.scalar.side_effect = [None, consultation, existing_payment]

    with pytest.raises(ConflictError) as exc_info:
        await initiate_consultation_payment(
            session=session,
            consultation_id=consultation.id,
            payload=PaymentCreateRequest(),
            current_user=patient,
            idempotency_key="ik_pay_dupe",
        )
    assert exc_info.value.code == "CONSULTATION_ALREADY_PAID"


@pytest.mark.asyncio
async def test_initiate_payment_amount_mismatch() -> None:
    """Payment fails if payload amount_minor does not match doctor's consultation fee."""
    patient = _make_user(role="patient")
    doctor_user = _make_user(role="doctor")
    doctor = _make_doctor(doctor_user.id, fee=2000)
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=doctor.id, status="confirmed"
    )

    session = _make_mock_session()
    session.scalar.side_effect = [None, consultation, None, doctor]

    with pytest.raises(ConflictError) as exc_info:
        await initiate_consultation_payment(
            session=session,
            consultation_id=consultation.id,
            payload=PaymentCreateRequest(amount_minor=1500),  # Doctor fee is 2000
            current_user=patient,
            idempotency_key="ik_pay_mismatch",
        )
    assert exc_info.value.code == "PAYMENT_AMOUNT_MISMATCH"


@pytest.mark.asyncio
async def test_initiate_payment_timeout_simulation() -> None:
    """Simulating timeout creates record with 'requires_reconciliation' status."""
    patient = _make_user(role="patient")
    doctor_user = _make_user(role="doctor")
    doctor = _make_doctor(doctor_user.id, fee=1000)
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=doctor.id, status="confirmed"
    )

    added_items: list[object] = []
    session = _make_mock_session(added_items)
    session.scalar.side_effect = [None, consultation, None, doctor]

    result = await initiate_consultation_payment(
        session=session,
        consultation_id=consultation.id,
        payload=PaymentCreateRequest(simulation="timeout"),
        current_user=patient,
        idempotency_key="ik_pay_timeout",
    )

    assert result.status == "requires_reconciliation"
    payments = [x for x in added_items if isinstance(x, Payment)]
    assert payments[0].status == "requires_reconciliation"


@pytest.mark.asyncio
async def test_get_payment_by_id_authorization() -> None:
    """Patient owner and admin can access; unrelated user is forbidden."""
    patient = _make_user(role="patient")
    stranger = _make_user(role="patient")
    admin = _make_user(role="admin")

    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=uuid.uuid4(), status="confirmed"
    )
    payment = Payment(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        amount_minor=1000,
        currency="INR",
        status="succeeded",
        provider="mock_provider",
        provider_reference="mock_pi_123",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payment.consultation = consultation

    session = _make_mock_session()
    session.scalar.return_value = payment

    # Owner access allowed
    res_owner = await get_payment_by_id(
        session=session, payment_id=payment.id, current_user=patient
    )
    assert res_owner.id == payment.id

    # Admin access allowed
    res_admin = await get_payment_by_id(session=session, payment_id=payment.id, current_user=admin)
    assert res_admin.id == payment.id

    # Unrelated patient forbidden
    with pytest.raises(ForbiddenError):
        await get_payment_by_id(session=session, payment_id=payment.id, current_user=stranger)


@pytest.mark.asyncio
async def test_get_payment_timeout_auto_reconciliation() -> None:
    """Fetching payment in requires_reconciliation resolves to succeeded via adapter."""
    patient = _make_user(role="patient")
    consultation = _make_consultation(
        patient_id=patient.id, doctor_id=uuid.uuid4(), status="confirmed"
    )
    payment = Payment(
        id=uuid.uuid4(),
        consultation_id=consultation.id,
        amount_minor=1000,
        currency="INR",
        status="requires_reconciliation",
        provider="mock_provider",
        provider_reference="mock_pi_recon",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    payment.consultation = consultation

    session = _make_mock_session()
    session.scalar.return_value = payment

    res = await get_payment_by_id(session=session, payment_id=payment.id, current_user=patient)
    assert res.status == "succeeded"
    assert payment.status == "succeeded"


@pytest.mark.asyncio
async def test_webhook_hmac_signature_validation() -> None:
    """Webhook requires authentic HMAC-SHA256 signature; rejects invalid signatures."""
    adapter = MockPaymentProviderAdapter()
    secret = MockPaymentProviderAdapter.DEFAULT_SECRET
    body = (
        b'{"event_id": "evt_1", "event_type": "payment.succeeded", '
        b'"provider_reference": "mock_pi_1"}'
    )

    valid_sig = adapter.generate_signature(body, secret)
    assert adapter.verify_webhook_signature(
        payload_bytes=body, signature_header=valid_sig, secret=secret
    )
    assert not adapter.verify_webhook_signature(
        payload_bytes=body, signature_header="invalid_sig", secret=secret
    )
    assert not adapter.verify_webhook_signature(
        payload_bytes=body, signature_header="", secret=secret
    )


@pytest.mark.asyncio
async def test_process_webhook_state_transitions() -> None:
    """Webhook transitions payment from pending to succeeded, and rejects invalid transitions."""
    payment = Payment(
        id=uuid.uuid4(),
        consultation_id=uuid.uuid4(),
        amount_minor=1000,
        currency="INR",
        status="pending",
        provider="mock_provider",
        provider_reference="mock_pi_hook",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    session = _make_mock_session()
    session.scalar.return_value = payment

    payload = WebhookEventPayload(
        event_id="evt_123",
        event_type="payment.succeeded",
        provider_reference="mock_pi_hook",
    )
    raw_body = json.dumps(payload.model_dump(mode="json")).encode("utf-8")
    sig = MockPaymentProviderAdapter.generate_signature(
        raw_body, MockPaymentProviderAdapter.DEFAULT_SECRET
    )

    # 1. Successful transition pending -> succeeded
    res = await process_provider_webhook(
        session=session,
        provider="mock_provider",
        payload_bytes=raw_body,
        signature_header=sig,
        payload=payload,
    )
    assert res["status"] == "processed"
    assert payment.status == "succeeded"

    # 2. Idempotent replay of same event
    replay_res = await process_provider_webhook(
        session=session,
        provider="mock_provider",
        payload_bytes=raw_body,
        signature_header=sig,
        payload=payload,
    )
    assert replay_res["status"] == "already_processed"

    # 3. Illegal transition: cannot fail an already succeeded payment
    fail_payload = WebhookEventPayload(
        event_id="evt_fail",
        event_type="payment.failed",
        provider_reference="mock_pi_hook",
    )
    fail_body = json.dumps(fail_payload.model_dump(mode="json")).encode("utf-8")
    fail_sig = MockPaymentProviderAdapter.generate_signature(
        fail_body, MockPaymentProviderAdapter.DEFAULT_SECRET
    )

    with pytest.raises(ConflictError) as exc_info:
        await process_provider_webhook(
            session=session,
            provider="mock_provider",
            payload_bytes=fail_body,
            signature_header=fail_sig,
            payload=fail_payload,
        )
    assert exc_info.value.code == "PAYMENT_INVALID_TRANSITION"


# ---------------------------------------------------------------------------
# HTTP Route Integration Tests (FastAPI TestClient)
# ---------------------------------------------------------------------------


def test_payment_endpoints_http_flow() -> None:
    """Full HTTP route tests: authentication, idempotency, webhook rejection."""
    app = create_app()
    patient = _make_user(role="patient")
    app.dependency_overrides[require_patient] = lambda: patient
    client = TestClient(app)

    consultation_id = uuid.uuid4()

    # 1. Missing Idempotency-Key header returns 400
    res = client.post(
        f"/api/v1/consultations/{consultation_id}/payments",
        json={"simulation": "success"},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"

    # 2. Webhook with invalid signature returns 401
    webhook_body = json.dumps(
        {
            "event_id": "evt_test",
            "event_type": "payment.succeeded",
            "provider_reference": "mock_pi_invalid",
        }
    )
    wh_res = client.post(
        "/api/v1/payments/webhooks/mock_provider",
        content=webhook_body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": "bad_sig"},
    )
    assert wh_res.status_code == 401


# ---------------------------------------------------------------------------
# PostgreSQL Live Tests (Transactions, Constraints, Idempotency Replay)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL not available")
@pytest.mark.asyncio
async def test_postgres_payment_lifecycle_end_to_end() -> None:
    """Live PostgreSQL test: atomic payment creation, idempotency replay, and webhook refunds."""
    session_factory = get_session_factory()
    now = datetime.now(UTC)

    async with session_factory() as session:
        # Create users
        patient_user = User(
            id=uuid.uuid4(),
            email_normalized=f"patient_pay_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="hash",
            role="patient",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        doctor_user = User(
            id=uuid.uuid4(),
            email_normalized=f"doc_pay_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="hash",
            role="doctor",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add_all([patient_user, doctor_user])
        await session.flush()

        doctor = Doctor(
            id=uuid.uuid4(),
            user_id=doctor_user.id,
            specialization="Panchakarma",
            license_number=f"DOC-{uuid.uuid4().hex[:8].upper()}",
            is_verified=True,
            consultation_fee_minor=1800,
            currency="INR",
            created_at=now,
            updated_at=now,
        )
        session.add(doctor)
        await session.flush()

        slot = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doctor.id,
            start_at=now,
            end_at=now + timedelta(minutes=30),
            status="booked",
            created_at=now,
            updated_at=now,
        )

        session.add(slot)
        await session.flush()

        consultation = Consultation(
            id=uuid.uuid4(),
            patient_id=patient_user.id,
            doctor_id=doctor.id,
            slot_id=slot.id,
            status="confirmed",
            created_at=now,
            updated_at=now,
        )
        session.add(consultation)
        await session.commit()

        consultation_id = consultation.id
        patient_id = patient_user.id

    # 1. Initiate payment in live PostgreSQL
    idempotency_key = f"ik_live_pay_{uuid.uuid4().hex}"
    async with session_factory() as session:
        patient_db = await session.get(User, patient_id)
        assert patient_db is not None

        res_1 = await initiate_consultation_payment(
            session=session,
            consultation_id=consultation_id,
            payload=PaymentCreateRequest(),
            current_user=patient_db,
            idempotency_key=idempotency_key,
        )
        await session.commit()

        assert res_1.status == "succeeded"
        assert res_1.amount_minor == 1800
        payment_id = res_1.id
        provider_ref = res_1.provider_reference

    # 2. Idempotency replay with same key
    async with session_factory() as session:
        patient_db = await session.get(User, patient_id)
        assert patient_db is not None

        res_2 = await initiate_consultation_payment(
            session=session,
            consultation_id=consultation_id,
            payload=PaymentCreateRequest(),
            current_user=patient_db,
            idempotency_key=idempotency_key,
        )
        assert res_2.id == payment_id
        assert res_2.status == "succeeded"

    # 3. Process webhook refund in live PostgreSQL
    async with session_factory() as session:
        refund_payload = WebhookEventPayload(
            event_id=f"evt_refund_{uuid.uuid4().hex[:6]}",
            event_type="payment.refunded",
            provider_reference=provider_ref,
        )
        raw_body = json.dumps(refund_payload.model_dump(mode="json")).encode("utf-8")
        sig = MockPaymentProviderAdapter.generate_signature(
            raw_body, MockPaymentProviderAdapter.DEFAULT_SECRET
        )

        wh_res = await process_provider_webhook(
            session=session,
            provider="mock_provider",
            payload_bytes=raw_body,
            signature_header=sig,
            payload=refund_payload,
        )
        await session.commit()
        assert wh_res["status"] == "processed"
        assert wh_res["payment_status"] == "refunded"

    # 4. Verify Payment status in PostgreSQL and check constraint chk_payments_status
    async with session_factory() as session:
        db_payment = await session.get(Payment, payment_id)
        assert db_payment is not None
        assert db_payment.status == "refunded"

        # Check constraint test: setting invalid status directly raises IntegrityError
        db_payment.status = "invalid_status_xyz"
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
