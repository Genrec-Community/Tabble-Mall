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


def test_prod_accepts_strong_config() -> None:
    s = _prod(jwt_secret=STRONG, otp_pepper=STRONG + "y", cookie_secure=True)
    assert s.env == "prod"


def test_default_dev_secrets_are_long_enough_for_hs256() -> None:
    s = Settings(env="dev", _env_file=None)  # type: ignore[call-arg]
    assert len(s.jwt_secret) >= 32 and len(s.otp_pepper) >= 32
