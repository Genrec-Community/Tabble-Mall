from urllib.parse import parse_qs, urlsplit

import httpx
import pyotp
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.errors import Conflict, Unprocessable
from mallt.modules.iam.seed import seed_admin

LOGIN = "/api/v1/auth/staff/login"
ME = "/api/v1/auth/staff/me"


def secret_of(uri: str) -> str:
    return parse_qs(urlsplit(uri).query)["secret"][0]


async def test_seed_admin_creates_a_platform_admin_who_can_log_in_with_totp(
    db_session: AsyncSession, client: httpx.AsyncClient
) -> None:
    uri = await seed_admin(
        db_session, username="Root", display_name="Root Admin", password="a-long-password"
    )
    assert uri.startswith("otpauth://totp/")

    r = await client.post(
        LOGIN,
        json={
            "username": "root",
            "password": "a-long-password",
            "totp_code": pyotp.TOTP(secret_of(uri)).now(),
        },
    )
    assert r.status_code == 200
    me = (
        await client.get(ME, headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    ).json()
    assert me["must_change_password"] is False and me["totp_enabled"] is True
    assert [g["role_key"] for g in me["grants"]] == ["platform_admin"]
    assert me["grants"][0]["scope_type"] == "platform"


async def test_seed_admin_twice_is_a_conflict(db_session: AsyncSession) -> None:
    await seed_admin(db_session, username="root", display_name="Root", password="a-long-password")
    with pytest.raises(Conflict) as e:
        await seed_admin(
            db_session, username="ROOT", display_name="Again", password="a-long-password"
        )
    assert e.value.code == "username_taken"


async def test_seed_admin_rejects_weak_password_and_bad_username(db_session: AsyncSession) -> None:
    with pytest.raises(Unprocessable) as weak:
        await seed_admin(db_session, username="root", display_name="Root", password="short")
    assert weak.value.code == "weak_password"
    with pytest.raises(Unprocessable) as bad:
        await seed_admin(
            db_session, username="a b", display_name="Root", password="a-long-password"
        )
    assert bad.value.code == "invalid_username"
