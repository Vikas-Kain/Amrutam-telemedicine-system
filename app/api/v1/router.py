"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, bookings, consultations, doctors, health, prescriptions

api_v1_router = APIRouter(prefix="/v1")

# Mount health routes under /api/v1/health
api_v1_router.include_router(health.router, tags=["health"])

# Mount auth routes under /api/v1/auth
api_v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Mount doctors routes under /api/v1/doctors
api_v1_router.include_router(doctors.router, prefix="/doctors", tags=["doctors"])

# Mount booking routes under /api/v1/bookings
api_v1_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])

# Mount consultation routes under /api/v1/consultations
api_v1_router.include_router(consultations.router, prefix="/consultations", tags=["consultations"])

# Mount prescription routes under /api/v1/prescriptions
api_v1_router.include_router(prescriptions.router, prefix="/prescriptions", tags=["prescriptions"])
