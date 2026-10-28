import pytest

from mallt.core.errors import AppError, Unauthorized
from mallt.modules.iam.google import GoogleIdTokenVerifier


async def test_unconfigured_google_login_is_a_503() -> None:
    with pytest.raises(AppError) as e:
        await GoogleIdTokenVerifier("").verify("anything")
    assert e.value.status == 503 and e.value.code == "google_not_configured"


async def test_garbage_token_is_rejected_without_any_network_call() -> None:
    with pytest.raises(Unauthorized) as e:
        await GoogleIdTokenVerifier("client-id.apps.googleusercontent.com").verify("not.a.jwt")
    assert e.value.code == "invalid_google_token"
