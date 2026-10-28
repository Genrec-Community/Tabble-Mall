import pytest

from mallt.cli import build_openapi, main
from mallt.core.errors import Conflict


def test_openapi_has_health_with_stable_operation_id() -> None:
    schema = build_openapi()
    op = schema["paths"]["/api/v1/health"]["get"]
    assert op["operationId"] == "health_get_health"
    assert schema["info"]["title"] == "MallT API"


def test_seed_admin_command_reads_the_password_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, str, str]] = []

    async def fake(settings: object, username: str, display_name: str, password: str) -> str:
        calls.append((username, display_name, password))
        return "otpauth://totp/MallT:root?secret=ABC"

    monkeypatch.setattr("mallt.cli.run_seed_admin", fake)
    monkeypatch.setenv("MALLT_ADMIN_PASSWORD", "a-long-password")

    code = main(["seed-admin", "--username", "root", "--display-name", "Root Admin"])

    assert code == 0 and calls == [("root", "Root Admin", "a-long-password")]
    out = capsys.readouterr().out
    assert "otpauth://totp/MallT:root?secret=ABC" in out and "a-long-password" not in out


def test_seed_admin_command_reports_an_existing_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake(settings: object, username: str, display_name: str, password: str) -> str:
        raise Conflict("username_taken")

    monkeypatch.setattr("mallt.cli.run_seed_admin", fake)
    monkeypatch.setenv("MALLT_ADMIN_PASSWORD", "a-long-password")

    assert main(["seed-admin", "--username", "root", "--display-name", "Root"]) == 1
    assert "already exists" in capsys.readouterr().err
