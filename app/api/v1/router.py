"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_v1_router = APIRouter(prefix="/v1")

# Mount health routes under /api/v1/health
api_v1_router.include_router(health.router, tags=["health"])

# Future feature routers (auth, doctors, bookings, consultations, prescriptions, payments, admin)
# will be included here as each milestone is implemented.
