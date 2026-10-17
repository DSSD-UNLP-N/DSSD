import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    secret_key: str,
    expires_minutes: int,
    cuit: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "username": username,
            "rol": role,
            "cuit": cuit,
            "iat": now,
            "exp": now + timedelta(minutes=expires_minutes),
        },
        secret_key,
        algorithm="HS256",
    )


def get_token_claims(token: str, secret_key: str) -> dict | None:
    try:
        return jwt.decode(token, secret_key, algorithms=["HS256"])
    except (InvalidTokenError, TypeError, ValueError):
        return None


def get_token_user_id(token: str, secret_key: str) -> int | None:
    try:
        subject = jwt.decode(token, secret_key, algorithms=["HS256"]).get("sub")
        return int(subject) if isinstance(subject, str) and subject.isdecimal() else None
    except (InvalidTokenError, TypeError, ValueError):
        return None
