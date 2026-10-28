import pytest
from pydantic import ValidationError

from mallt.core.config import Settings

STRONG = "x" * 40


def _prod(**kw: object) -> Settings:
    return Settings(env="prod", _env_file=None, **kw)  # type: ignore[call-arg]


def test_prod_refuses_default_secrets() -> None:
    with pytest.raises(ValidationError, match="jwt_secret"):
        _prod()


def test_prod_refuses_short_secrets() -> None:
    with pytest.raises(ValidationError, match="otp_pepper"):
        _prod(jwt_secret=STRONG, otp_pepper="short")


def test_prod_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError, match="cookie_secure"):
        _prod(jwt_secret=STRONG, otp_pepper=STRONG + "y", cookie_secure=False)


GOOD = {
    "jwt_secret": STRONG,
    "otp_pepper": STRONG + "y",
    "cookie_secure": True,
    "sms_backend": "fast2sms",
    "fast2sms_api_key": "key",
    "cors_origins": ["https://mallt.example"],
}


def test_prod_accepts_strong_config() -> None:
    assert _prod(**GOOD).env == "prod"


def test_prod_must_really_send_sms() -> None:
    with pytest.raises(ValidationError, match="sms_backend"):
        _prod(**{**GOOD, "sms_backend": "console"})


def test_prod_must_not_trust_localhost_origins() -> None:
    with pytest.raises(ValidationError, match="cors_origins"):
        _prod(**{**GOOD, "cors_origins": ["https://mallt.example", "http://localhost:3000"]})


def test_default_dev_secrets_are_long_enough_for_hs256() -> None:
    s = Settings(env="dev", _env_file=None)  # type: ignore[call-arg]
    assert len(s.jwt_secret) >= 32 and len(s.otp_pepper) >= 32
