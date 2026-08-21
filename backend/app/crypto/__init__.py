"""PENUMBRA cryptographic layer.

Public surface:
    CKKSEngine, CKKSParameters -- the homomorphic encryption trust boundary
    HomomorphicOps             -- server-side computation over ciphertexts
    PostQuantumChannel         -- session establishment and ciphertext authentication
"""

from .ckks_engine import (
    DEEP_PARAMETERS,
    DEFAULT_PARAMETERS,
    LIGHT_PARAMETERS,
    CiphertextError,
    CKKSEngine,
    CKKSParameters,
    CryptoError,
    InsecureParameters,
    SecretKeyUnavailable,
)
from .security_utils import SealError, seal, unseal

__all__ = [
    "CKKSEngine",
    "CKKSParameters",
    "DEFAULT_PARAMETERS",
    "DEEP_PARAMETERS",
    "LIGHT_PARAMETERS",
    "CryptoError",
    "InsecureParameters",
    "SecretKeyUnavailable",
    "CiphertextError",
    "SealError",
    "seal",
    "unseal",
]
