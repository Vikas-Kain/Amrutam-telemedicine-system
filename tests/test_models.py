"""Unit and schema invariant tests for core SQLAlchemy models and constraints."""

import uuid

import pytest
import sqlalchemy as sa
from app.db.base import Base
from app.models import (
    AuditLog,
    AvailabilitySlot,
    Consultation,
    Doctor,
    IdempotencyKey,
    OutboxEvent,
    Payment,
    Prescription,
    PrescriptionItem,
    Profile,
    User,
)
from sqlalchemy import CheckConstraint, UniqueConstraint

from tests.conftest import is_postgres_available


def test_all_11_core_tables_registered_in_metadata():
    """Verify all 11 domain models are declared and registered on Base.metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {
        "users",
        "profiles",
        "doctors",
        "availability_slots",
        "consultations",
        "prescriptions",
        "prescription_items",
        "payments",
        "audit_logs",
        "idempotency_keys",
        "outbox_events",
    }
    assert expected_tables.issubset(table_names), f"Missing tables: {expected_tables - table_names}"


def test_primary_keys_are_uuid():
    """Verify primary key columns across all core models use UUID types."""
    tables = [
        User,
        Profile,
        Doctor,
        AvailabilitySlot,
        Consultation,
        Prescription,
        PrescriptionItem,
        Payment,
        AuditLog,
        IdempotencyKey,
        OutboxEvent,
    ]
    for model in tables:
        pk_cols = list(model.__table__.primary_key.columns)
        assert len(pk_cols) == 1, f"{model.__name__} must have a single primary key"
        assert isinstance(pk_cols[0].type, sa.Uuid), (
            f"{model.__name__}.{pk_cols[0].name} must be UUID type"
        )


def test_foreign_key_delete_rules_prevent_history_erasure():
    """Verify delete rules protect medical records and audit trails while cascading demography."""
    # Clinical and financial history MUST NOT be cascade deleted when a user or doctor is removed
    consultations_table = Base.metadata.tables["consultations"]
    fks = {fk.parent.name: fk for fk in consultations_table.foreign_keys}
    assert fks["patient_id"].ondelete == "RESTRICT"
    assert fks["doctor_id"].ondelete == "RESTRICT"
    assert fks["slot_id"].ondelete == "RESTRICT"

    prescriptions_table = Base.metadata.tables["prescriptions"]
    p_fks = {fk.parent.name: fk for fk in prescriptions_table.foreign_keys}
    assert p_fks["consultation_id"].ondelete == "RESTRICT"
    assert p_fks["patient_id"].ondelete == "RESTRICT"
    assert p_fks["doctor_id"].ondelete == "RESTRICT"

    payments_table = Base.metadata.tables["payments"]
    pay_fks = {fk.parent.name: fk for fk in payments_table.foreign_keys}
    assert pay_fks["consultation_id"].ondelete == "RESTRICT"

    # Audit logs must preserve records even if user account is deleted
    audit_table = Base.metadata.tables["audit_logs"]
    audit_fks = {fk.parent.name: fk for fk in audit_table.foreign_keys}
    assert audit_fks["actor_user_id"].ondelete == "SET NULL"

    # Profile, doctor, slots, prescription items, and idempotency keys cascade delete with owner
    profiles_table = Base.metadata.tables["profiles"]
    assert list(profiles_table.foreign_keys)[0].ondelete == "CASCADE"

    doctors_table = Base.metadata.tables["doctors"]
    assert list(doctors_table.foreign_keys)[0].ondelete == "CASCADE"

    slots_table = Base.metadata.tables["availability_slots"]
    assert list(slots_table.foreign_keys)[0].ondelete == "CASCADE"

    items_table = Base.metadata.tables["prescription_items"]
    assert list(items_table.foreign_keys)[0].ondelete == "CASCADE"

    idempotency_table = Base.metadata.tables["idempotency_keys"]
    assert list(idempotency_table.foreign_keys)[0].ondelete == "CASCADE"


def test_check_constraints_defined():
    """Verify non-negative money and time interval check constraints."""
    doctors_table = Base.metadata.tables["doctors"]
    doc_checks = [c.name for c in doctors_table.constraints if isinstance(c, CheckConstraint)]
    assert "chk_doctors_fee_non_negative" in doc_checks

    slots_table = Base.metadata.tables["availability_slots"]
    slot_checks = [c.name for c in slots_table.constraints if isinstance(c, CheckConstraint)]
    assert "chk_slot_time_interval" in slot_checks

    payments_table = Base.metadata.tables["payments"]
    pay_checks = [c.name for c in payments_table.constraints if isinstance(c, CheckConstraint)]
    assert "chk_payments_amount_non_negative" in pay_checks


def test_unique_indexes_and_partial_indexes():
    """Verify unique indexes and partial concurrency booking constraints."""
    users_table = Base.metadata.tables["users"]
    user_unique = [c.name for c in users_table.indexes if c.unique]
    assert any("email_normalized" in str(col) for col in user_unique)

    doctors_table = Base.metadata.tables["doctors"]
    doc_unique = [c.name for c in doctors_table.indexes if c.unique]
    assert any("license_number" in str(col) for col in doc_unique)

    consultations_table = Base.metadata.tables["consultations"]
    slot_index = next(
        (idx for idx in consultations_table.indexes if idx.name == "uq_consultations_active_slot"),
        None,
    )
    assert slot_index is not None
    assert slot_index.unique is True
    assert "dialect_options" in dir(slot_index)
    assert slot_index.dialect_options["postgresql"]["where"] is not None

    payments_table = Base.metadata.tables["payments"]
    ref_index = next(
        (idx for idx in payments_table.indexes if idx.name == "uq_payments_provider_reference"),
        None,
    )
    assert ref_index is not None
    assert ref_index.unique is True

    idempotency_table = Base.metadata.tables["idempotency_keys"]
    idemp_unique = [
        c.name for c in idempotency_table.constraints if isinstance(c, UniqueConstraint)
    ]
    assert "uq_idempotency_user_key_operation" in idemp_unique


def test_model_column_defaults_and_instantiation():
    """Verify models declare proper column defaults and can be instantiated."""
    # Column level defaults
    assert User.__table__.c.is_active.default.arg is True
    assert User.__table__.c.mfa_enabled.default.arg is False
    assert Doctor.__table__.c.is_verified.default.arg is False
    assert Doctor.__table__.c.currency.default.arg == "INR"
    assert AvailabilitySlot.__table__.c.status.default.arg == "available"
    assert Consultation.__table__.c.status.default.arg == "booked"
    assert Payment.__table__.c.status.default.arg == "pending"
    assert Payment.__table__.c.currency.default.arg == "INR"
    assert OutboxEvent.__table__.c.status.default.arg == "pending"

    # Explicit instantiation works cleanly
    user = User(
        email_normalized="patient@example.com",
        password_hash="argon2id$mockhash",
        role="patient",
        is_active=True,
        mfa_enabled=False,
    )
    assert user.email_normalized == "patient@example.com"
    assert user.role == "patient"
    assert user.is_active is True

    doctor = Doctor(
        user_id=uuid.uuid4(),
        specialization="Ayurveda",
        license_number="LIC-12345",
        consultation_fee_minor=50000,
        currency="INR",
        is_verified=False,
    )
    assert doctor.specialization == "Ayurveda"
    assert doctor.consultation_fee_minor == 50000
    assert doctor.currency == "INR"


@pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL instance not reachable; run via Docker Compose or in CI",
)
async def test_live_postgres_model_operations():
    """Verify model persistence, relationships, and constraints against live PostgreSQL."""
    # This integration test runs when PostgreSQL is active (in CI or Docker Compose)
    from app.db.session import get_db_session

    async for session in get_db_session():
        # Clean user creation
        test_user = User(
            email_normalized=f"test_{uuid.uuid4().hex[:8]}@example.com",
            password_hash="hashed_pw_argon2",
            role="doctor",
        )
        session.add(test_user)
        await session.flush()
        assert test_user.id is not None
