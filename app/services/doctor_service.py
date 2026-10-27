"""Doctor profile retrieval and searchable listing business services."""

import logging
import math
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models.doctor import Doctor
from app.models.user import Profile, User

logger = logging.getLogger(__name__)


async def list_doctors(
    session: AsyncSession,
    *,
    specialization: str | None = None,
    name: str | None = None,
    is_verified: bool | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Doctor], int, int]:
    """Retrieve a paginated, deterministically sorted list of doctors matching optional filters.

    Returns:
        tuple[list[Doctor], int, int]: (doctor_records, total_matching_records, total_pages)
    """
    # Base query joining user and profile for search criteria and name retrieval
    base_query = select(Doctor).outerjoin(Doctor.user).outerjoin(User.profile)

    # Count query sharing the exact same joins and filters
    count_query = (
        select(func.count(Doctor.id))
        .select_from(Doctor)
        .outerjoin(Doctor.user)
        .outerjoin(User.profile)
    )

    # 1. Filter: Specialization
    if specialization and specialization.strip():
        spec_term = f"%{specialization.strip()}%"
        base_query = base_query.where(Doctor.specialization.ilike(spec_term))
        count_query = count_query.where(Doctor.specialization.ilike(spec_term))

    # 2. Filter: Verification Status
    if is_verified is not None:
        base_query = base_query.where(Doctor.is_verified.is_(is_verified))
        count_query = count_query.where(Doctor.is_verified.is_(is_verified))

    # 3. Filter: Name Substring
    if name and name.strip():
        name_term = f"%{name.strip()}%"
        base_query = base_query.where(Profile.full_name.ilike(name_term))
        count_query = count_query.where(Profile.full_name.ilike(name_term))

    # 4. Filter: General Keyword Search (name, specialization, or bio)
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        search_filter = or_(
            Profile.full_name.ilike(search_term),
            Doctor.specialization.ilike(search_term),
            Doctor.bio.ilike(search_term),
        )
        base_query = base_query.where(search_filter)
        count_query = count_query.where(search_filter)

    # Execute total count
    total = (await session.scalar(count_query)) or 0
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    # Deterministic sorting (created_at DESC, id DESC) and bounded pagination
    offset = (page - 1) * page_size
    paged_query = (
        base_query.options(selectinload(Doctor.user).selectinload(User.profile))
        .order_by(Doctor.created_at.desc(), Doctor.id.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await session.scalars(paged_query)
    doctors = list(result.all())

    return doctors, total, total_pages


async def get_doctor_by_id(session: AsyncSession, doctor_id: uuid.UUID) -> Doctor:
    """Retrieve a single doctor by unique identifier with associated profile attributes.

    Raises:
        NotFoundError: If no doctor with the provided ID exists.
    """
    stmt = (
        select(Doctor)
        .where(Doctor.id == doctor_id)
        .options(selectinload(Doctor.user).selectinload(User.profile))
    )
    doctor = await session.scalar(stmt)
    if doctor is None:
        raise NotFoundError("Doctor not found.", code="DOCTOR_NOT_FOUND")

    return doctor
