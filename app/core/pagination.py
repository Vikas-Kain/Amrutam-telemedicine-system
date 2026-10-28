"""Standardized pagination parameter helpers and bounds validation."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Query

from app.core.config import get_settings
from app.core.errors import BadRequestError


@dataclass(frozen=True)
class PaginationParams:
    """Encapsulates validated pagination query parameters."""

    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        """Calculate SQL OFFSET value (0-indexed)."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """Calculate SQL LIMIT value."""
        return self.page_size


def validate_pagination_bounds(
    page: int,
    page_size: int,
    max_page_size: int | None = None,
) -> None:
    """Validate pagination query parameters against application limits.

    Raises BadRequestError (HTTP 400) if bounds are breached.
    """
    settings = get_settings()
    max_allowed = max_page_size or settings.max_page_size

    if page < 1:
        raise BadRequestError(
            message="page must be greater than or equal to 1.",
            code="INVALID_PAGINATION_PAGE",
        )
    if page_size < 1 or page_size > max_allowed:
        raise BadRequestError(
            message=f"page_size must be between 1 and {max_allowed}.",
            code="INVALID_PAGINATION_PAGE_SIZE",
        )


def get_pagination(
    page: Annotated[int, Query(ge=1, description="Page number (1-indexed, minimum 1)")] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=100, description="Items per page (minimum 1, maximum 100)"),
    ] = 20,
) -> PaginationParams:
    """FastAPI dependency resolving and validating standard pagination parameters."""
    return PaginationParams(page=page, page_size=page_size)
