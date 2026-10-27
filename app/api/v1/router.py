"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, doctors, health

api_v1_router = APIRouter(prefix="/v1")

# Mount health routes under /api/v1/health
api_v1_router.include_router(health.router, tags=["health"])

# Mount auth routes under /api/v1/auth
api_v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Mount doctors routes under /api/v1/doctors
api_v1_router.include_router(doctors.router, prefix="/doctors", tags=["doctors"])
