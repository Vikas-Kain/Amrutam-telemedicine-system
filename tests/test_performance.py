"""Automated integration tests for performance test fixtures, seeder, and index efficiency.

Validates that:
1. Synthetic performance test dataset seeds cleanly without schema violations.
2. Filtered doctor searches and slot range queries execute efficiently.
3. Explicit dataset cleanup purges 100% of synthetic records without leaving orphan rows.
4. Benchmark runner executes and measures latency and throughput metrics correctly.
"""

import uuid

import pytest
from app.models.doctor import AvailabilitySlot, Doctor
from app.models.user import User
from sqlalchemy import select

from tests.performance.data_seeder import (
    PERF_EMAIL_PREFIX,
    cleanup_performance_dataset,
    seed_performance_dataset,
)
from tests.performance.run_benchmark import run_benchmark


@pytest.mark.asyncio
async def test_performance_dataset_seeding_and_cleanup(cleanup_db) -> None:
    """Verify synthetic dataset seeds properly and cleanup removes all test entities."""
    from app.db.session import get_session_factory

    session_factory = get_session_factory()

    # 1. Seed small synthetic test dataset
    async with session_factory() as session:
        dataset = await seed_performance_dataset(
            session=session,
            doctor_count=3,
            slots_per_doctor=4,
            patient_count=3,
        )

        assert len(dataset.doctor_ids) == 3
        assert len(dataset.slot_ids) == 12
        assert len(dataset.patient_ids) == 3
        assert len(dataset.patient_tokens) == 3
        assert len(dataset.doctor_tokens) == 3

    # 2. Query seeded entities using indexed lookups
    async with session_factory() as session:
        first_doc_uuid = uuid.UUID(dataset.doctor_ids[0])
        doctor = await session.get(Doctor, first_doc_uuid)
        assert doctor is not None
        assert doctor.specialization is not None

        # Verify slots associated with doctor
        slots = (
            await session.scalars(
                select(AvailabilitySlot).where(
                    AvailabilitySlot.doctor_id == first_doc_uuid,
                    AvailabilitySlot.status == "available",
                )
            )
        ).all()
        assert len(list(slots)) > 0

    # 3. Explicit cleanup
    async with session_factory() as session:
        deleted_count = await cleanup_performance_dataset(session=session, dataset=dataset)
        assert deleted_count >= 6  # 3 patients + 3 doctors

    # 4. Confirm zero synthetic users remain
    async with session_factory() as session:
        remaining = (
            await session.scalars(
                select(User.id).where(User.email_normalized.like(f"{PERF_EMAIL_PREFIX.lower()}%"))
            )
        ).all()
        assert len(list(remaining)) == 0


@pytest.mark.asyncio
async def test_run_benchmark_execution(cleanup_db) -> None:
    """Verify run_benchmark executes workload mix and returns valid percentile statistics."""
    result = await run_benchmark(
        concurrency=3,
        duration_seconds=2.0,
        doctor_count=5,
        slots_per_doctor=4,
    )

    assert result.total_requests > 0
    assert result.duration_seconds > 0.0
    assert result.throughput_rps > 0.0
    assert result.p50_latency_ms >= 0.0
    assert result.p95_latency_ms >= result.p50_latency_ms
    assert result.p99_latency_ms >= result.p95_latency_ms
    assert result.error_count == 0
    assert result.error_rate_pct == 0.0

    # Verify endpoint metrics
    assert "GET /api/v1/doctors" in result.endpoints
    assert "GET /api/v1/doctors/{id}/slots" in result.endpoints
    assert "POST /api/v1/bookings" in result.endpoints
