"""Encryption keys, secure sessions and encrypted portfolio storage."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile, status

from ....crypto.ckks_engine import CKKSEngine
from ....models.audit_log import AuditAction, AuditSeverity
from ....models.encryption_key import EncryptionKey
from ....schemas.common import Message
from ....schemas.crypto_schema import (
    ContextInfoOut,
    EncryptionKeyOut,
    PublicContextUpload,
    SessionOut,
    SessionRequest,
)
from ....schemas.portfolio_schema import (
    CsvValidationResult,
    EncryptedPortfolioUpload,
    PortfolioOut,
    PortfolioWithCiphertext,
)
from ....services.audit_service import AuditService
from ....services.keystore_service import SecretKeyRejected
from ....services.portfolio_service import PortfolioService, ValidationFailed
from ..dependencies import Channel, CurrentUser, DbSession, Keystore, Req

router = APIRouter()


# ---------------------------------------------------------------------------
# Encryption keys
# ---------------------------------------------------------------------------


@router.post("/keys", response_model=EncryptionKeyOut, status_code=status.HTTP_201_CREATED)
def register_public_key(
    payload: PublicContextUpload,
    current_user: CurrentUser,
    db: DbSession,
    keystore: Keystore,
    request: Req,
) -> EncryptionKey:
    """Register a CKKS **public** context generated in the browser.

    The server validates that the blob carries no secret key and that its
    parameters meet 128-bit security, then stores it. A blob containing a
    secret key is refused with ``secret_key_rejected`` and recorded as a
    critical audit event -- the user's key is compromised at that point and
    should be rotated.

    Note there is deliberately no ``generate-keypair`` endpoint. Key generation
    on the server would hand it the secret, and no amount of promising not to
    keep it would be verifiable by the user.
    """
    try:
        key = keystore.register(db, current_user.id, payload.public_context, label=payload.label)
    except SecretKeyRejected:
        AuditService.record(
            db,
            AuditAction.KEY_REJECTED_SECRET_PRESENT,
            actor_user_id=current_user.id,
            request=request,
            severity=AuditSeverity.CRITICAL,
        )
        db.commit()
        raise

    AuditService.record(
        db,
        AuditAction.KEY_REGISTERED,
        actor_user_id=current_user.id,
        resource_type="encryption_key",
        resource_id=key.id,
        request=request,
        fingerprint=key.fingerprint,
        poly_modulus_degree=key.poly_modulus_degree,
        security_level_bits=key.security_level_bits,
        megabytes=round(key.context_bytes / 1e6, 2),
    )
    db.commit()
    return key


@router.get("/keys", response_model=list[EncryptionKeyOut])
def list_keys(current_user: CurrentUser, db: DbSession) -> list[EncryptionKey]:
    """Every key this user has registered, newest first."""
    return (
        db.query(EncryptionKey)
        .filter(EncryptionKey.user_id == current_user.id)
        .order_by(EncryptionKey.created_at.desc())
        .all()
    )


@router.get("/keys/active", response_model=EncryptionKeyOut)
def active_key(current_user: CurrentUser, db: DbSession, keystore: Keystore) -> EncryptionKey:
    """The key new portfolios will be bound to."""
    return keystore.active_key(db, current_user.id)


@router.post("/keys/inspect", response_model=ContextInfoOut)
def inspect_context(payload: PublicContextUpload, _current_user: CurrentUser) -> ContextInfoOut:
    """Report a context's real parameters without storing it.

    Lets the client confirm it built the context it intended -- particularly
    whether rotation keys are present, which decides whether server-side
    reductions will work -- before committing to a 35 MB upload.
    """
    info = CKKSEngine.from_public_context(payload.public_context).inspect_context()
    return ContextInfoOut(**info.as_dict())  # type: ignore[arg-type]


@router.delete("/keys/{key_id}", response_model=Message)
def revoke_key(
    key_id: str, current_user: CurrentUser, db: DbSession, keystore: Keystore, request: Req
) -> Message:
    """Deactivate a key.

    The blob is retained: portfolios encrypted under it would otherwise become
    permanently unusable by the pipeline.
    """
    key = (
        db.query(EncryptionKey)
        .filter(EncryptionKey.id == key_id, EncryptionKey.user_id == current_user.id)
        .one_or_none()
    )
    if key is None:
        raise ValidationFailed(f"no key {key_id} for this account")
    keystore.revoke(db, key)
    AuditService.record(
        db,
        AuditAction.KEY_REVOKED,
        actor_user_id=current_user.id,
        resource_type="encryption_key",
        resource_id=key.id,
        request=request,
        fingerprint=key.fingerprint,
    )
    db.commit()
    return Message(message=f"key {key.fingerprint} revoked")


# ---------------------------------------------------------------------------
# Secure sessions
# ---------------------------------------------------------------------------


@router.post("/session", response_model=SessionOut)
def open_session(
    payload: SessionRequest,
    current_user: CurrentUser,
    db: DbSession,
    keystore: Keystore,
    channel: Channel,
    request: Req,
) -> SessionOut:
    """Open a session bound to this user's active key.

    Returns a MAC key the client uses to authenticate each ciphertext it
    uploads. That MAC gives integrity and origin authentication; confidentiality
    already comes from CKKS. When BB84 simulation is enabled the response also
    carries the simulated exchange statistics -- a demonstration of the
    protocol, not a source of key material.
    """
    key = keystore.active_key(db, current_user.id)
    result = channel.establish_session(
        current_user.id, key.fingerprint, bb84_qubits=payload.bb84_qubits
    )
    AuditService.record(
        db,
        AuditAction.SESSION_ESTABLISHED,
        actor_user_id=current_user.id,
        resource_type="session",
        resource_id=str(result["session_id"]),
        request=request,
        key_fingerprint=result["key_fingerprint"],
    )
    db.commit()
    return SessionOut(**result)  # type: ignore[arg-type]


@router.delete("/session/{session_id}", response_model=Message)
def close_session(
    session_id: str, current_user: CurrentUser, db: DbSession, channel: Channel, request: Req
) -> Message:
    """Close a session."""
    channel.close_session(session_id)
    AuditService.record(
        db,
        AuditAction.SESSION_CLOSED,
        actor_user_id=current_user.id,
        resource_type="session",
        resource_id=session_id,
        request=request,
    )
    db.commit()
    return Message(message="session closed")


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------


@router.post("/", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
def upload_encrypted_portfolio(
    payload: EncryptedPortfolioUpload,
    current_user: CurrentUser,
    db: DbSession,
    keystore: Keystore,
    request: Req,
):
    """Store a portfolio that the browser has already encrypted.

    This is the only upload path that preserves the privacy guarantee. The
    request body contains tickers in plaintext -- the server needs them to
    interpret slot order and to look up public market data -- and ciphertexts
    for everything else.
    """
    portfolio = PortfolioService.create(
        db,
        current_user.id,
        tickers=payload.tickers,
        holdings_ciphertext=payload.holdings_ciphertext,
        cost_basis_ciphertext=payload.cost_basis_ciphertext,
        name=payload.name,
        keystore=keystore,
    )
    AuditService.record(
        db,
        AuditAction.PORTFOLIO_UPLOADED,
        actor_user_id=current_user.id,
        resource_type="portfolio",
        resource_id=portfolio.id,
        request=request,
        n_assets=portfolio.n_assets,
        ciphertext_megabytes=round(portfolio.ciphertext_bytes / 1e6, 3),
    )
    db.commit()
    return _to_out(portfolio)


@router.post("/validate-csv", response_model=CsvValidationResult)
def validate_csv(_current_user: CurrentUser, file: UploadFile = File(...)) -> CsvValidationResult:
    """Check a portfolio CSV's shape without storing anything.

    The quantities parsed here are discarded immediately; only the ticker list
    and row count are returned. This exists so the browser can report format
    errors before spending seconds on encryption, and it is the one place the
    server touches a CSV -- it never persists what it parses.
    """
    content = file.file.read()
    try:
        parsed = PortfolioService.parse_csv(content)
    except ValidationFailed as exc:
        return CsvValidationResult(
            valid=False, n_assets=0, tickers=[], has_cost_basis=False, problems=str(exc).split("; ")
        )
    return CsvValidationResult(
        valid=True,
        n_assets=len(parsed),
        tickers=list(parsed.tickers),
        has_cost_basis=parsed.cost_basis is not None,
    )


@router.get("/current", response_model=PortfolioWithCiphertext)
def current_portfolio(current_user: CurrentUser, db: DbSession):
    """The active portfolio with its ciphertexts, for client-side decryption."""
    portfolio = PortfolioService.current(db, current_user.id)
    return _to_out(portfolio, with_ciphertext=True)


@router.get("/", response_model=list[PortfolioOut])
def list_portfolios(current_user: CurrentUser, db: DbSession, limit: int = 20):
    """Portfolio history, newest first."""
    return [_to_out(p) for p in PortfolioService.history(db, current_user.id, limit=limit)]


@router.get("/{portfolio_id}", response_model=PortfolioWithCiphertext)
def get_portfolio(portfolio_id: str, current_user: CurrentUser, db: DbSession):
    """A specific portfolio, scoped to its owner."""
    return _to_out(PortfolioService.get(db, current_user.id, portfolio_id), with_ciphertext=True)


@router.delete("/{portfolio_id}", response_model=Message)
def delete_portfolio(
    portfolio_id: str, current_user: CurrentUser, db: DbSession, request: Req
) -> Message:
    """Permanently delete a portfolio and its ciphertexts."""
    PortfolioService.delete(db, current_user.id, portfolio_id)
    AuditService.record(
        db,
        AuditAction.PORTFOLIO_DELETED,
        actor_user_id=current_user.id,
        resource_type="portfolio",
        resource_id=portfolio_id,
        request=request,
    )
    db.commit()
    return Message(message="portfolio deleted")


def _to_out(portfolio, *, with_ciphertext: bool = False) -> dict:
    """Serialise a portfolio, expanding the JSON ticker column."""
    data = {
        "id": portfolio.id,
        "name": portfolio.name,
        "tickers": portfolio.tickers,
        "n_assets": portfolio.n_assets,
        "ciphertext_bytes": portfolio.ciphertext_bytes,
        "encryption_key_id": portfolio.encryption_key_id,
        "is_active": portfolio.is_active,
        "created_at": portfolio.created_at,
    }
    if with_ciphertext:
        data["holdings_ciphertext"] = portfolio.holdings_ciphertext
        data["cost_basis_ciphertext"] = portfolio.cost_basis_ciphertext
    return data
