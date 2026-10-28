import re

import pyotp
import pytest

from mallt.core.config import Settings
from mallt.core.errors import Unauthorized
from mallt.core.ids import uuid7
from mallt.core.security import (
    create_access_token,
    decode_access_token,
    hash_opaque,
    hash_otp,
    hash_password,
    new_opaque_token,
    new_otp,
    new_temp_password,
    new_totp_secret,
    password_needs_rehash,
    totp_uri,
    verify_password,
    verify_totp,
)


def _settings(**kw: object) -> Settings:
    return Settings(env="test", _env_file=None, **kw)  # type: ignore[call-arg]


def test_password_round_trip_and_mismatch() -> None:
    h = hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery")
    assert not verify_password(h, "wrong")
    assert not password_needs_rehash(h)


def test_verify_password_never_raises_on_garbage_hash() -> None:
    assert verify_password("not-a-hash", "x") is False


def test_access_token_round_trip() -> None:
    s, sub, sid = _settings(), uuid7(), uuid7()
    claims = decode_access_token(s, create_access_token(s, sub=sub, typ="staff", sid=sid))
    assert (claims.sub, claims.typ, claims.sid) == (sub, "staff", sid)
    assert claims.exp > 0


def test_token_signed_with_other_secret_is_rejected() -> None:
    token = create_access_token(
        _settings(jwt_secret="a" * 32), sub=uuid7(), typ="staff", sid=uuid7()
    )
    with pytest.raises(Unauthorized) as e:
        decode_access_token(_settings(jwt_secret="b" * 32), token)
    assert e.value.code == "invalid_token"


def test_expired_token_is_rejected() -> None:
    s = _settings(access_ttl_s=-10)
    token = create_access_token(s, sub=uuid7(), typ="customer", sid=uuid7())
    with pytest.raises(Unauthorized) as e:
        decode_access_token(s, token)
    assert e.value.code == "invalid_token"


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c"])
def test_garbage_token_is_rejected(junk: str) -> None:
    with pytest.raises(Unauthorized):
        decode_access_token(_settings(), junk)


def test_token_carries_no_permissions() -> None:
    import jwt

    s = _settings()
    token = create_access_token(s, sub=uuid7(), typ="staff", sid=uuid7())
    payload = jwt.decode(token, options={"verify_signature": False})
    assert set(payload) == {"iss", "sub", "typ", "sid", "iat", "exp"}


def test_opaque_token_hash_matches() -> None:
    raw, hashed = new_opaque_token()
    assert hashed == hash_opaque(raw) and raw != hashed and len(raw) >= 48
    assert new_opaque_token()[0] != raw


def test_totp_round_trip() -> None:
    secret = new_totp_secret()
    assert verify_totp(secret, pyotp.TOTP(secret).now())
    assert not verify_totp(secret, "000000") or pyotp.TOTP(secret).now() == "000000"
    assert totp_uri(secret, "asha").startswith("otpauth://totp/")
    assert "MallT" in totp_uri(secret, "asha")


def test_otp_is_six_digits_and_hash_is_per_phone() -> None:
    otp = new_otp()
    assert re.fullmatch(r"\d{6}", otp)
    s = _settings()
    assert hash_otp(s, "9361899061", otp) == hash_otp(s, "9361899061", otp)
    assert hash_otp(s, "9361899061", otp) != hash_otp(s, "9361899062", otp)
    assert hash_otp(s, "9361899061", otp) != hash_otp(s, "9361899061", "000000")
    assert hash_otp(s, "9361899061", otp) != hash_otp(
        _settings(otp_pepper="x" * 32), "9361899061", otp
    )


def test_temp_password_is_strong_enough() -> None:
    a, b = new_temp_password(), new_temp_password()
    assert len(a) >= 16 and a != b
