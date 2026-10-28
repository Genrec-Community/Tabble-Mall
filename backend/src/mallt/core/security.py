"""Password hashing, JWTs, opaque tokens, TOTP and OTP helpers. Pure: no I/O."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from mallt.core.config import Settings
from mallt.core.errors import Unauthorized

IdentityType = Literal["staff", "customer"]

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True)
class AccessClaims:
    sub: uuid.UUID
    typ: IdentityType
    sid: uuid.UUID  # the refresh-token family, so revoking a session kills its access tokens
    exp: int


def create_access_token(
    settings: Settings, *, sub: uuid.UUID, typ: IdentityType, sid: uuid.UUID
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": settings.jwt_issuer,
        "sub": str(sub),
        "typ": typ,
        "sid": str(sid),
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_ttl_s),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        data = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        typ = data["typ"]
        if typ not in ("staff", "customer"):
            raise ValueError("bad typ")
        return AccessClaims(
            sub=uuid.UUID(data["sub"]), typ=typ, sid=uuid.UUID(data["sid"]), exp=int(data["exp"])
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise Unauthorized("invalid_token", "Invalid or expired access token.") from exc


def hash_opaque(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_opaque_token() -> tuple[str, str]:
    """A random token for the client plus the hash we store."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_opaque(raw)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="MallT")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(settings: Settings, phone: str, otp: str) -> str:
    return hmac.new(
        settings.otp_pepper.encode(), f"{phone}:{otp}".encode(), hashlib.sha256
    ).hexdigest()


def new_temp_password() -> str:
    return secrets.token_urlsafe(12)
