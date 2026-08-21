"""Key registration and secure-session models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PublicContextUpload(BaseModel):
    """A client's CKKS public context.

    The server rejects this payload outright if the blob contains a secret key.
    """

    public_context: str = Field(
        description="Base64 CKKS context serialised with save_secret_key=False",
        repr=False,
    )
    label: str | None = Field(default=None, max_length=128)


class ContextInfoOut(BaseModel):
    """Parameters read back off an uploaded context."""

    poly_modulus_degree: int
    total_coeff_modulus_bits: int
    multiplicative_depth: int
    global_scale_bits: int
    slot_count: int
    has_galois_keys: bool
    has_relin_keys: bool
    security_level_bits: int


class EncryptionKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    fingerprint: str
    context_bytes: int
    poly_modulus_degree: int
    total_coeff_modulus_bits: int
    global_scale_bits: int
    security_level_bits: int
    has_galois_keys: bool
    multiplicative_depth: int
    slot_count: int
    is_active: bool
    label: str | None
    created_at: datetime


class SessionRequest(BaseModel):
    """Open an authenticated session bound to the caller's active key."""

    bb84_qubits: int = Field(default=2048, ge=16, le=65536)


class SessionOut(BaseModel):
    session_id: str
    user_id: str
    key_fingerprint: str
    created_at: int
    expires_at: int
    mac_key: str = Field(description="Base64 HMAC key for authenticating ciphertexts", repr=False)
    bb84: dict | None = Field(
        default=None,
        description="Statistics from the BB84 simulation, when enabled. Demonstration only.",
    )
