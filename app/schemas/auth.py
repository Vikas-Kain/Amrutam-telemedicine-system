"""Authentication and user registration schemas."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import normalize_email


class UserRegisterRequest(BaseModel):
    """Payload schema for new patient account registration."""

    email: EmailStr = Field(
        ...,
        description="Patient unique email address",
        examples=["patient@example.com"],
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Account password (min 8, max 128 characters)",
        examples=["SecurePassw0rd!"],
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Patient full legal name",
        examples=["Aarav Sharma"],
    )
    phone: str | None = Field(
        default=None,
        max_length=32,
        description="Optional contact telephone number",
        examples=["+919876543210"],
    )
    date_of_birth: date | None = Field(
        default=None,
        description="Optional date of birth (YYYY-MM-DD)",
        examples=["1990-05-15"],
    )

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email_input(cls, v: EmailStr) -> str:
        """Ensure email is consistently normalized to lowercase with whitespace stripped."""
        return normalize_email(str(v))

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        """Ensure full name is non-empty after stripping whitespace."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Full name cannot be blank or whitespace-only.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password_not_blank(cls, v: str) -> str:
        """Ensure password is not composed solely of whitespace."""
        if not v.strip():
            raise ValueError("Password cannot consist solely of whitespace.")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob_not_future(cls, v: date | None) -> date | None:
        """Ensure date of birth is not in the future."""
        if v is not None and v > date.today():
            raise ValueError("Date of birth cannot be in the future.")
        return v


class ProfileResponse(BaseModel):
    """Public demographic profile details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique profile identifier")
    full_name: str = Field(..., description="Patient full name")
    phone: str | None = Field(default=None, description="Contact phone number")
    date_of_birth: date | None = Field(default=None, description="Date of birth")
    created_at: datetime = Field(..., description="Profile creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Profile last update timestamp (UTC)")


class UserResponse(BaseModel):
    """Safe user account representation that guarantees sensitive fields are omitted."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID = Field(..., description="Unique user identifier")
    email: str = Field(
        ...,
        validation_alias="email_normalized",
        description="User verified normalized email address",
    )
    role: str = Field(..., description="Assigned role (e.g. 'patient')")
    is_active: bool = Field(..., description="Account active status")
    mfa_enabled: bool = Field(..., description="Whether MFA is enabled on account")
    created_at: datetime = Field(..., description="Account creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Account last update timestamp (UTC)")
    profile: ProfileResponse | None = Field(default=None, description="Associated user profile")
