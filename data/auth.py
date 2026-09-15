"""
StudyMatch - password hashing for user_account.password_hash.

stdlib only (hashlib.pbkdf2_hmac, a NIST-recommended KDF) - this project's
scale doesn't need an extra dependency (bcrypt/passlib) for this. Each
password gets its own random salt; the stored string is "salt_hex$hash_hex"
so verify_password() never needs the salt passed separately.
"""

import hashlib
import secrets

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, _, digest_hex = stored.partition("$")
    if not digest_hex:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return secrets.compare_digest(check.hex(), digest_hex)
