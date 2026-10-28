import httpx
import pytest

from mallt.core.config import Settings
from mallt.core.errors import AppError
from mallt.modules.iam.sms import ConsoleSms, Fast2Sms, make_sms_sender


def handler_returning(
    payload: dict[str, object], status: int = 200
) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return seen, httpx.MockTransport(handle)


async def test_fast2sms_sends_the_key_in_a_header_never_in_the_url() -> None:
    seen, transport = handler_returning({"return": True, "request_id": "abc", "message": ["sent"]})
    await Fast2Sms("SECRET-KEY", transport=transport).send_otp("9361899061", "123456")

    (request,) = seen
    assert request.method == "GET" and request.url.host == "www.fast2sms.com"
    assert request.url.path == "/dev/bulkV2"
    assert dict(request.url.params) == {
        "route": "otp",
        "variables_values": "123456",
        "numbers": "9361899061",
    }
    assert request.headers["authorization"] == "SECRET-KEY"
    assert "SECRET-KEY" not in str(request.url)


async def test_fast2sms_failure_responses_become_502() -> None:
    for payload, status in (({"return": False, "message": ["bad"]}, 200), ({"message": "x"}, 500)):
        _, transport = handler_returning(payload, status)
        with pytest.raises(AppError) as e:
            await Fast2Sms("k", transport=transport).send_otp("9361899061", "123456")
        assert e.value.status == 502 and e.value.code == "sms_failed"


async def test_fast2sms_network_error_becomes_502() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(AppError) as e:
        await Fast2Sms("k", transport=httpx.MockTransport(boom)).send_otp("9361899061", "1")
    assert e.value.status == 502


def test_factory_picks_the_backend_from_settings() -> None:
    dev = Settings(env="dev", sms_backend="console", _env_file=None)  # type: ignore[call-arg]
    real = Settings(env="dev", sms_backend="fast2sms", fast2sms_api_key="k", _env_file=None)  # type: ignore[call-arg]
    assert isinstance(make_sms_sender(dev), ConsoleSms)
    assert isinstance(make_sms_sender(real), Fast2Sms)


def test_fast2sms_backend_without_a_key_is_refused() -> None:
    bad = Settings(env="dev", sms_backend="fast2sms", fast2sms_api_key="", _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError):
        make_sms_sender(bad)


async def test_console_sms_prints_the_otp_only_in_dev(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    await ConsoleSms(Settings(env="dev", _env_file=None)).send_otp("9361899061", "424242")  # type: ignore[call-arg]
    assert "424242" in caplog.text
    caplog.clear()
    await ConsoleSms(Settings(env="test", _env_file=None)).send_otp("9361899061", "424242")  # type: ignore[call-arg]
    assert "424242" not in caplog.text and "9361899061" not in caplog.text
