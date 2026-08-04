"""
Small helper for encrypting per-clinic WhatsApp credentials before they're
stored in the database (Clinic.twilio_auth_token, Clinic.meta_access_token,
etc). Uses Fernet (symmetric, authenticated encryption) from `cryptography`.

In production, set CREDENTIALS_ENCRYPTION_KEY to a stable, secret Fernet key
(generate once with `Fernet.generate_key()` and never rotate casually - doing
so invalidates every stored credential). If it isn't set, we derive a key
from SECRET_KEY so local/demo installs still work without extra setup.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    key = current_app.config.get("CREDENTIALS_ENCRYPTION_KEY")
    if not key:
        # Derive a stable 32-byte key from SECRET_KEY so this works without
        # extra configuration in development.
        secret = current_app.config.get("SECRET_KEY", "dev-secret-change-me")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    if isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def encrypt_value(plain_text: str) -> str:
    if not plain_text:
        return ""
    return _get_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_value(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        return _get_fernet().decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        current_app.logger.warning("Could not decrypt a stored credential - was CREDENTIALS_ENCRYPTION_KEY changed?")
        return ""
