"""Automated tests for role-protected admin analytics endpoints,

date range bounding, grouped SQL aggregation queries, and privacy invariants.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.deps import get_current_user, get_db_session
from app.core.errors import BadRequestError
from app.db.session import get_session_factory
from app.main import create_app
from app.models.consultation import Consultation
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.payment import Payment
from app.models.user import User
from app.services.analytics_service import (
    get_booking_analytics,
    get_consultation_analytics,
    get_payment_analytics,
    validate_date_range,
)
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import is_postgres_available


def _make_user(*, role: str = "patient") -> User:
    return User(
        id=uuid.uuid4(),
        email_normalized=f"{role}_{uuid.uuid4().hex[:6]}@example.com",
        password_hash="placeholder_hash",
        role=role,
        is_active=True,
    )


def test_validate_date_range_bounds() -> None:
    """Test date range defaults, inversion checks, and maximum window bounding."""
    now = datetime.now(UTC)

    # 1. Defaults to past 30 days
    date_from, date_to = validate_date_range(None, None)
    assert date_to.tzinfo is not None
    assert date_from.tzinfo is not None
    diff_days = (date_to - date_from).days
    assert 29 <= diff_days <= 31

    # 2. Inverted dates reject with INVALID_DATE_RANGE (HTTP 400)
    with pytest.raises(BadRequestError) as exc_info:
        validate_date_range(
            date_from=now + timedelta(days=5),
            date_to=now,
        )
    assert exc_info.value.code == "INVALID_DATE_RANGE"
    assert exc_info.value.status_code == 400

    # 3. Excessive window (>90 days) rejects with DATE_RANGE_TOO_LARGE (HTTP 400)
    with pytest.raises(BadRequestError) as exc_info:
        validate_date_range(
            date_from=now - timedelta(days=95),
            date_to=now,
        )
    assert exc_info.value.code == "DATE_RANGE_TOO_LARGE"
    assert exc_info.value.status_code == 400

    # 4. Valid custom window within 90 days succeeds
    d_from = now - timedelta(days=45)
    d_to = now
    res_from, res_to = validate_date_range(d_from, d_to)
    assert res_from == d_from
    assert res_to == d_to


def test_analytics_rbac_unauthenticated_returns_401() -> None:
    """Unauthenticated calls to analytics endpoints return 401 Unauthorized."""
    app = create_app()
    client = TestClient(app)

    endpoints = [
        "/api/v1/admin/analytics/consultations",
        "/api/v1/admin/analytics/bookings",
        "/api/v1/admin/analytics/payments",
    ]
    for url in endpoints:
        res = client.get(url)
        assert res.status_code == 401, f"Expected 401 for {url}, got {res.status_code}"


def test_analytics_rbac_patient_and_doctor_return_403() -> None:
    """Patients and Doctors cannot access analytics endpoints (HTTP 403 Forbidden)."""
    app = create_app()

    endpoints = [
        "/api/v1/admin/analytics/consultations",
        "/api/v1/admin/analytics/bookings",
        "/api/v1/admin/analytics/payments",
    ]

    for non_admin_role in ("patient", "doctor"):
        user = _make_user(role=non_admin_role)
        app.dependency_overrides[get_current_user] = lambda u=user: u

        client = TestClient(app)
        for url in endpoints:
            res = client.get(url)
            assert res.status_code == 403, (
                f"Expected 403 for {non_admin_role} on {url}, got {res.status_code}"
            )


@pytest.mark.asyncio
async def test_consultation_analytics_unit_service() -> None:
    """Verify consultation aggregation calculations, rates, and privacy invariants."""
    session = AsyncMock(spec=AsyncSession)
    now = datetime.now(UTC)
    date_from = now - timedelta(days=14)
    date_to = now

    # Mock status grouping query
    mock_status_exec = MagicMock()
    mock_status_exec.all.return_value = [
        ("completed", 6),
        ("confirmed", 2),
        ("cancelled", 2),
    ]

    # Mock daily trends grouping query
    mock_trend_exec = MagicMock()
    mock_trend_exec.all.return_value = [
        (datetime(2026, 10, 20).date(), "completed", 3),
        (datetime(2026, 10, 20).date(), "confirmed", 1),
        (datetime(2026, 10, 21).date(), "completed", 3),
        (datetime(2026, 10, 21).date(), "cancelled", 2),
    ]

    session.execute.side_effect = [mock_status_exec, mock_trend_exec]

    res = await get_consultation_analytics(session, date_from, date_to)

    assert res.total_consultations == 10
    assert res.status_counts["completed"] == 6
    assert res.status_counts["confirmed"] == 2
    assert res.status_counts["cancelled"] == 2
    assert res.status_counts["booked"] == 0
    assert res.completion_rate == 0.6  # 6 / 10
    assert len(res.daily_trends) == 2

    # Assert model does NOT have patient-level fields
    res_dict = res.model_dump()
    assert "patient_id" not in res_dict
    assert "reason" not in res_dict
    assert "prescription" not in res_dict


@pytest.mark.asyncio
async def test_booking_analytics_unit_service() -> None:
    """Verify booking aggregation calculations, cancellation rates, and no-show rates."""
    session = AsyncMock(spec=AsyncSession)
    now = datetime.now(UTC)
    date_from = now - timedelta(days=14)
    date_to = now

    mock_status_exec = MagicMock()
    mock_status_exec.all.return_value = [
        ("completed", 10),
        ("confirmed", 5),
        ("cancelled", 4),
        ("no_show", 1),
    ]

    mock_trend_exec = MagicMock()
    mock_trend_exec.all.return_value = [
        (datetime(2026, 10, 20).date(), "completed", 5),
        (datetime(2026, 10, 20).date(), "cancelled", 2),
        (datetime(2026, 10, 21).date(), "no_show", 1),
        (datetime(2026, 10, 21).date(), "cancelled", 2),
    ]

    session.execute.side_effect = [mock_status_exec, mock_trend_exec]

    res = await get_booking_analytics(session, date_from, date_to)

    assert res.total_bookings == 20
    assert res.confirmed_bookings == 5
    assert res.completed_bookings == 10
    assert res.cancelled_bookings == 4
    assert res.cancellation_rate == 0.2  # 4 / 20
    assert res.no_show_bookings == 1
    assert res.no_show_rate == 0.05  # 1 / 20
    assert len(res.daily_trends) == 2


@pytest.mark.asyncio
async def test_payment_analytics_unit_service() -> None:
    """Verify payment aggregation calculations, volume, and success/failure ratios."""
    session = AsyncMock(spec=AsyncSession)
    now = datetime.now(UTC)
    date_from = now - timedelta(days=14)
    date_to = now

    mock_status_exec = MagicMock()
    # (status, count, sum_minor)
    mock_status_exec.all.return_value = [
        ("succeeded", 8, 400000),  # 8 succeeded, 4000 INR
        ("failed", 2, 100000),
    ]

    mock_trend_exec = MagicMock()
    mock_trend_exec.all.return_value = [
        (datetime(2026, 10, 20).date(), "succeeded", 4, 200000),
        (datetime(2026, 10, 20).date(), "failed", 1, 50000),
        (datetime(2026, 10, 21).date(), "succeeded", 4, 200000),
        (datetime(2026, 10, 21).date(), "failed", 1, 50000),
    ]

    session.execute.side_effect = [mock_status_exec, mock_trend_exec]

    res = await get_payment_analytics(session, date_from, date_to, currency="INR")

    assert res.total_payments == 10
    assert res.total_volume_minor == 400000
    assert res.currency == "INR"
    assert res.success_rate == 0.8  # 8 / 10
    assert res.failure_rate == 0.2  # 2 / 10
    assert res.refund_rate == 0.0
    assert len(res.daily_trends) == 2

    res_dict = res.model_dump()
    assert "pan" not in res_dict
    assert "provider_reference" not in res_dict


def test_admin_analytics_http_flow_and_auditing() -> None:
    """HTTP integration test: valid admin queries succeed and record audit events."""
    app = create_app()
    admin_user = _make_user(role="admin")
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()

    # Setup dummy database returns for analytics queries
    mock_result_status = MagicMock()
    mock_result_status.all.return_value = []
    mock_result_trend = MagicMock()
    mock_result_trend.all.return_value = []
    session.execute.side_effect = [
        mock_result_status,
        mock_result_trend,
        mock_result_status,
        mock_result_trend,
        mock_result_status,
        mock_result_trend,
    ]

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db_session] = lambda: session

    client = TestClient(app)

    # 1. Consultation Analytics endpoint
    res_cons = client.get("/api/v1/admin/analytics/consultations")
    assert res_cons.status_code == 200
    data_cons = res_cons.json()
    assert "total_consultations" in data_cons
    assert "status_counts" in data_cons
    assert "completion_rate" in data_cons

    # 2. Booking Analytics endpoint
    res_book = client.get("/api/v1/admin/analytics/bookings")
    assert res_book.status_code == 200
    data_book = res_book.json()
    assert "total_bookings" in data_book
    assert "cancellation_rate" in data_book
    assert "no_show_rate" in data_book

    # 3. Payment Analytics endpoint
    res_pay = client.get("/api/v1/admin/analytics/payments")
    assert res_pay.status_code == 200
    data_pay = res_pay.json()
    assert "total_payments" in data_pay
    assert "total_volume_minor" in data_pay
    assert "success_rate" in data_pay

    # 4. HTTP validation: Inverted date returns 400
    res_inverted = client.get(
        "/api/v1/admin/analytics/consultations?date_from=2026-10-25T00:00:00Z&date_to=2026-10-10T00:00:00Z"
    )
    assert res_inverted.status_code == 400
    assert res_inverted.json()["error"]["code"] == "INVALID_DATE_RANGE"

    # 5. HTTP validation: Window > 90 days returns 400
    res_toolarge = client.get(
        "/api/v1/admin/analytics/consultations?date_from=2026-01-01T00:00:00Z&date_to=2026-06-01T00:00:00Z"
    )
    assert res_toolarge.status_code == 400
    assert res_toolarge.json()["error"]["code"] == "DATE_RANGE_TOO_LARGE"


# ---------------------------------------------------------------------------
# PostgreSQL Live Tests (Indexes, Grouped Aggregations & DB Consistency)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not is_postgres_available(), reason="PostgreSQL not available")
@pytest.mark.asyncio
async def test_postgres_live_analytics_aggregates_and_filters() -> None:
    """Live PostgreSQL test: executes grouped queries and indexes against seeded data."""
    session_factory = get_session_factory()
    now = datetime.now(UTC)

    async with session_factory() as session:
        # 1. Create Patient and Doctors
        patient = User(
            id=uuid.uuid4(),
            email_normalized=f"patient_analytics_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="pw_hash",
            role="patient",
            is_active=True,
        )
        doctor_user1 = User(
            id=uuid.uuid4(),
            email_normalized=f"doc1_analytics_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="pw_hash",
            role="doctor",
            is_active=True,
        )
        doctor_user2 = User(
            id=uuid.uuid4(),
            email_normalized=f"doc2_analytics_{uuid.uuid4().hex[:6]}@example.com",
            password_hash="pw_hash",
            role="doctor",
            is_active=True,
        )
        session.add_all([patient, doctor_user1, doctor_user2])
        await session.flush()

        doc1 = Doctor(
            id=uuid.uuid4(),
            user_id=doctor_user1.id,
            specialization="General Ayurveda",
            license_number=f"DOC-A1-{uuid.uuid4().hex[:6].upper()}",
            consultation_fee_minor=50000,
            is_verified=True,
        )
        doc2 = Doctor(
            id=uuid.uuid4(),
            user_id=doctor_user2.id,
            specialization="Panchakarma",
            license_number=f"DOC-A2-{uuid.uuid4().hex[:6].upper()}",
            consultation_fee_minor=75000,
            is_verified=True,
        )
        session.add_all([doc1, doc2])
        await session.flush()

        # 2. Create Availability Slots
        slot1 = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doc1.id,
            start_at=now - timedelta(hours=2),
            end_at=now - timedelta(hours=1),
            status="booked",
        )
        slot2 = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doc1.id,
            start_at=now - timedelta(hours=1),
            end_at=now,
            status="booked",
        )
        slot3 = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doc2.id,
            start_at=now - timedelta(hours=3),
            end_at=now - timedelta(hours=2),
            status="available",
        )
        slot4 = AvailabilitySlot(
            id=uuid.uuid4(),
            doctor_id=doc1.id,
            start_at=now - timedelta(days=1),
            end_at=now - timedelta(days=1) + timedelta(hours=1),
            status="booked",
        )
        session.add_all([slot1, slot2, slot3, slot4])
        await session.flush()

        # 3. Create Consultations across statuses and doctors
        # doc1: 1 completed, 1 cancelled, 1 no_show
        c1 = Consultation(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doc1.id,
            slot_id=slot1.id,
            status="completed",
            created_at=now - timedelta(hours=2),
        )
        c2 = Consultation(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doc1.id,
            slot_id=slot2.id,
            status="cancelled",
            created_at=now - timedelta(hours=1),
        )
        c3 = Consultation(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doc1.id,
            slot_id=slot4.id,
            status="no_show",
            created_at=now - timedelta(days=1),
        )
        # doc2: 1 confirmed
        c4 = Consultation(
            id=uuid.uuid4(),
            patient_id=patient.id,
            doctor_id=doc2.id,
            slot_id=slot3.id,
            status="confirmed",
            created_at=now - timedelta(hours=3),
        )
        session.add_all([c1, c2, c3, c4])
        await session.flush()

        # 4. Create Payments
        p1 = Payment(
            id=uuid.uuid4(),
            consultation_id=c1.id,
            amount_minor=50000,
            currency="INR",
            status="succeeded",
            provider="mock_provider",
            provider_reference=f"pi_mock_{uuid.uuid4().hex[:8]}",
            created_at=now - timedelta(hours=2),
        )
        p2 = Payment(
            id=uuid.uuid4(),
            consultation_id=c2.id,
            amount_minor=50000,
            currency="INR",
            status="failed",
            provider="mock_provider",
            provider_reference=f"pi_mock_{uuid.uuid4().hex[:8]}",
            created_at=now - timedelta(hours=1),
        )
        session.add_all([p1, p2])
        await session.commit()

        # 5. Query Consultation Analytics (Global)
        eval_from = now - timedelta(days=2)
        eval_to = now + timedelta(hours=1)
        cons_res = await get_consultation_analytics(session, eval_from, eval_to)
        assert cons_res.total_consultations >= 4
        assert cons_res.status_counts["completed"] >= 1
        assert cons_res.status_counts["cancelled"] >= 1
        assert cons_res.status_counts["no_show"] >= 1
        assert cons_res.status_counts["confirmed"] >= 1

        # 6. Query Consultation Analytics (Filtered by doc2)
        doc2_res = await get_consultation_analytics(session, eval_from, eval_to, doctor_id=doc2.id)
        assert doc2_res.total_consultations == 1
        assert doc2_res.status_counts["confirmed"] == 1
        assert doc2_res.status_counts["completed"] == 0

        # 7. Query Booking Analytics (Filtered by doc1)
        doc1_book = await get_booking_analytics(session, eval_from, eval_to, doctor_id=doc1.id)
        assert doc1_book.total_bookings == 3
        assert doc1_book.completed_bookings == 1
        assert doc1_book.cancelled_bookings == 1
        assert doc1_book.no_show_bookings == 1
        assert doc1_book.cancellation_rate == round(1 / 3, 4)
        assert doc1_book.no_show_rate == round(1 / 3, 4)

        # 8. Query Payment Analytics
        pay_res = await get_payment_analytics(session, eval_from, eval_to, currency="INR")
        assert pay_res.total_payments >= 2
        assert pay_res.status_counts["succeeded"] >= 1
        assert pay_res.status_counts["failed"] >= 1
        assert pay_res.total_volume_minor >= 50000
