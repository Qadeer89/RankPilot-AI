"""Symmetric encryption for OAuth/connector tokens at rest
(SECURITY_SPECIFICATION.md #3).

Never store a provider access/refresh token in plaintext. Generate a key
with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

and set it as RANKPILOT_TOKEN_ENCRYPTION_KEY in the server environment.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class TokenEncryptionNotConfigured(RuntimeError):
    pass


def _get_fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise TokenEncryptionNotConfigured(
            "RANKPILOT_TOKEN_ENCRYPTION_KEY is not set; cannot encrypt or decrypt OAuth tokens."
        )
    return Fernet(key.encode("utf-8"))


def encrypt_text(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_text(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Could not decrypt stored token; it may be corrupt or the key rotated.") from exc
