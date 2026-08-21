"""Authentication request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ..services.user_service import UserService


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=72)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        problems = UserService.validate_password_strength(v)
        if problems:
            raise ValueError("password " + "; ".join(problems))
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    """Issued on register, login and refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserPublic(BaseModel):
    """A user as the owner sees themselves."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None

    @field_validator("role", mode="before")
    @classmethod
    def _enum_value(cls, v: object) -> object:
        return getattr(v, "value", v)
