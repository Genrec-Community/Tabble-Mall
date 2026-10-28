import httpx
import pyotp
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus
from mallt.core.rbac import Scope
from mallt.core.security import new_totp_secret
from mallt.modules.audit.models import AuditLog
from mallt.modules.iam.authz import AuthzService
from mallt.modules.iam.models import RefreshToken, StaffUser
from tests.factories import (
    DEFAULT_PASSWORD,
    make_mall,
    make_org,
    make_staff,
    make_store,
    store_scope,
)

URL = "/api/v1/auth/staff"
CSRF = {"X-Requested-With": "mallt"}


async def login(
    client: httpx.AsyncClient,
    username: str,
    password: str = DEFAULT_PASSWORD,
    totp: str | None = None,
) -> httpx.Response:
    body = {"username": username, "password": password}
    if totp:
        body["totp_code"] = totp
    return await client.post(f"{URL}/login", json=body)


def bearer(r: httpx.Response) -> dict[str, str]:
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def cookie(name: str, value: str) -> dict[str, str]:
    return {**CSRF, "Cookie": f"{name}={value}"}


async def test_login_returns_token_and_httponly_cookie(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    r = await login(client, "asha")

    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer" and r.json()["expires_in"] == 900
    set_cookie = r.headers["set-cookie"].lower()
    assert "mallt_srt=" in set_cookie and "httponly" in set_cookie
    assert "samesite=lax" in set_cookie and "path=/api/v1/auth" in set_cookie
    me = await client.get(f"{URL}/me", headers=bearer(r))
    assert me.status_code == 200 and me.json()["username"] == "asha"


async def test_username_is_trimmed_and_case_insensitive(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "ravi.k")
    r = await login(client, " Ravi.K ")
    assert r.status_code == 200
    me = await client.get(f"{URL}/me", headers=bearer(r))
    assert me.json()["username"] == "ravi.k"


async def test_wrong_password_and_unknown_user_look_identical(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    wrong = await login(client, "asha", "not-the-password")
    unknown = await login(client, "nobody")
    assert wrong.status_code == unknown.status_code == 401
    strip = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
    assert strip(wrong) == strip(unknown) and wrong.json()["code"] == "invalid_credentials"


async def test_eleventh_login_attempt_in_window_is_rate_limited(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    for _ in range(10):
        assert (await login(client, "asha", "wrong-password")).status_code == 401
    r = await login(client, "asha")  # even the right password is refused now
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


async def test_suspended_account_cannot_log_in(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha", status=ActiveStatus.SUSPENDED)
    r = await login(client, "asha")
    assert r.status_code == 401 and r.json()["code"] == "account_suspended"


async def test_refresh_requires_csrf_header(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    r = await login(client, "asha")
    raw = r.cookies["mallt_srt"]
    bad = await client.post(f"{URL}/refresh", headers={"Cookie": f"mallt_srt={raw}"})
    assert bad.status_code == 403 and bad.json()["code"] == "csrf"


async def test_refresh_rotates_and_reuse_revokes_the_whole_family(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    first = (await login(client, "asha")).cookies["mallt_srt"]

    r2 = await client.post(f"{URL}/refresh", headers=cookie("mallt_srt", first))
    assert r2.status_code == 200
    second = r2.cookies["mallt_srt"]
    assert second != first and r2.json()["access_token"]

    replay = await client.post(f"{URL}/refresh", headers=cookie("mallt_srt", first))
    assert replay.status_code == 401 and replay.json()["code"] == "refresh_reuse"

    # The family is revoked, so the legitimately rotated token is dead too, and so is the
    # access token issued by it.
    after = await client.post(f"{URL}/refresh", headers=cookie("mallt_srt", second))
    assert after.status_code == 401 and after.json()["code"] == "invalid_refresh"
    me = await client.get(f"{URL}/me", headers=bearer(r2))
    assert me.status_code == 401


async def test_refresh_with_garbage_or_expired_token_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    assert (
        await client.post(f"{URL}/refresh", headers=cookie("mallt_srt", "junk"))
    ).status_code == 401
    assert (await client.post(f"{URL}/refresh", headers=CSRF)).status_code == 401  # no cookie

    raw = (await login(client, "asha")).cookies["mallt_srt"]
    # Expiring "at creation" makes every issued token already expired.
    await db_session.execute(update(RefreshToken).values(expires_at=RefreshToken.created_at))
    r = await client.post(f"{URL}/refresh", headers=cookie("mallt_srt", raw))
    assert r.status_code == 401 and r.json()["code"] == "invalid_refresh"


async def test_logout_kills_the_session_and_its_access_token(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    r = await login(client, "asha")
    raw = r.cookies["mallt_srt"]

    out = await client.post(f"{URL}/logout", headers=cookie("mallt_srt", raw))
    assert out.status_code == 204
    assert (
        "mallt_srt" in out.headers["set-cookie"]
        and "max-age=0" in out.headers["set-cookie"].lower()
    )
    assert (await client.get(f"{URL}/me", headers=bearer(r))).status_code == 401
    assert (
        await client.post(f"{URL}/refresh", headers=cookie("mallt_srt", raw))
    ).status_code == 401
    # logging out twice is harmless
    assert (await client.post(f"{URL}/logout", headers=cookie("mallt_srt", raw))).status_code == 204


async def test_logout_all_revokes_every_session(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    a, b = await login(client, "asha"), await login(client, "asha")
    assert (await client.post(f"{URL}/logout-all", headers=bearer(a))).status_code == 204
    assert (await client.get(f"{URL}/me", headers=bearer(a))).status_code == 401
    assert (await client.get(f"{URL}/me", headers=bearer(b))).status_code == 401


async def test_totp_required_when_enabled(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    secret = new_totp_secret()
    await make_staff(db_session, "asha", totp_secret=secret)

    missing = await login(client, "asha")
    assert missing.status_code == 401 and missing.json()["code"] == "totp_required"
    wrong = await login(
        client, "asha", totp="000000" if pyotp.TOTP(secret).now() != "000000" else "111111"
    )
    assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_totp"
    ok = await login(client, "asha", totp=pyotp.TOTP(secret).now())
    assert ok.status_code == 200


async def test_platform_admin_without_totp_cannot_log_in(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "root", [("platform_admin", Scope.platform())])
    r = await login(client, "root")
    assert r.status_code == 401 and r.json()["code"] == "totp_enrollment_required"


async def test_must_change_password_gates_everything_but_me_password_logout(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "fresh", must_change_password=True)
    r = await login(client, "fresh")
    h = bearer(r)

    assert (await client.get(f"{URL}/me", headers=h)).json()["must_change_password"] is True
    blocked = await client.get(f"{URL}/sessions", headers=h)
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"

    done = await client.post(
        f"{URL}/password",
        headers=h,
        json={"current_password": DEFAULT_PASSWORD, "new_password": "a-brand-new-pass"},
    )
    assert done.status_code == 204
    assert (await client.get(f"{URL}/sessions", headers=h)).status_code == 200
    assert (await login(client, "fresh", "a-brand-new-pass")).status_code == 200
    assert (await login(client, "fresh", DEFAULT_PASSWORD)).status_code == 401


async def test_change_password_validates_and_revokes_other_sessions(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    here, elsewhere = await login(client, "asha"), await login(client, "asha")

    wrong = await client.post(
        f"{URL}/password",
        headers=bearer(here),
        json={"current_password": "nope", "new_password": "a-brand-new-pass"},
    )
    assert wrong.status_code == 400 and wrong.json()["code"] == "invalid_current_password"
    short = await client.post(
        f"{URL}/password",
        headers=bearer(here),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "short"},
    )
    assert short.status_code == 422
    same = await client.post(
        f"{URL}/password",
        headers=bearer(here),
        json={"current_password": DEFAULT_PASSWORD, "new_password": DEFAULT_PASSWORD},
    )
    assert same.status_code == 422 or same.status_code == 400

    ok = await client.post(
        f"{URL}/password",
        headers=bearer(here),
        json={"current_password": DEFAULT_PASSWORD, "new_password": "a-brand-new-pass"},
    )
    assert ok.status_code == 204
    assert (await client.get(f"{URL}/me", headers=bearer(here))).status_code == 200
    assert (await client.get(f"{URL}/me", headers=bearer(elsewhere))).status_code == 401
    actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
    assert "staff.password_changed" in actions


async def test_totp_setup_and_confirm_then_login_needs_code(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    h = bearer(await login(client, "asha"))

    setup = await client.post(f"{URL}/totp/setup", headers=h)
    assert setup.status_code == 200 and setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    secret = setup.json()["secret"]
    assert (await login(client, "asha")).status_code == 200  # not enabled until confirmed

    assert (
        await client.post(f"{URL}/totp/confirm", headers=h, json={"code": "000000"})
    ).status_code in (400, 401)
    assert (
        await client.post(f"{URL}/totp/confirm", headers=h, json={"code": pyotp.TOTP(secret).now()})
    ).status_code == 204
    assert (await login(client, "asha")).json()["code"] == "totp_required"
    assert (await login(client, "asha", totp=pyotp.TOTP(secret).now())).status_code == 200
    staff = (
        await db_session.execute(select(StaffUser).where(StaffUser.username == "asha"))
    ).scalar_one()
    await db_session.refresh(staff)
    assert staff.totp_enabled is True


async def test_suspending_a_user_locks_out_a_still_valid_access_token(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    staff = await make_staff(db_session, "asha")
    h = bearer(await login(client, "asha"))
    assert (await client.get(f"{URL}/me", headers=h)).status_code == 200

    await db_session.execute(
        update(StaffUser).where(StaffUser.id == staff.id).values(status=ActiveStatus.SUSPENDED)
    )
    # Staff management does this on every status change; with Redis the principal is cached.
    await AuthzService(db_session, app.state.kv).invalidate(staff.id)
    r = await client.get(f"{URL}/me", headers=h)
    assert r.status_code == 401 and r.json()["code"] == "account_suspended"


async def test_refresh_for_a_suspended_user_is_refused(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    staff = await make_staff(db_session, "asha")
    raw = (await login(client, "asha")).cookies["mallt_srt"]
    await db_session.execute(
        update(StaffUser).where(StaffUser.id == staff.id).values(status=ActiveStatus.SUSPENDED)
    )
    r = await client.post(f"{URL}/refresh", headers=cookie("mallt_srt", raw))
    assert r.status_code == 401 and r.json()["code"] == "account_suspended"


async def test_me_lists_grants_with_scope_ids_and_permissions(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    store = await make_store(db_session, mall)
    await make_staff(db_session, "cashier", [("store_staff", store_scope(store))])

    me = (await client.get(f"{URL}/me", headers=bearer(await login(client, "cashier")))).json()
    (grant,) = me["grants"]
    assert grant["role_key"] == "store_staff" and grant["scope_type"] == "store"
    assert (grant["organization_id"], grant["mall_id"], grant["store_id"]) == (
        str(org.id),
        str(mall.id),
        str(store.id),
    )
    assert "store.order.update" in grant["permissions"]


async def test_sessions_lists_active_sessions_and_marks_the_current_one(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    a, _b = await login(client, "asha"), await login(client, "asha")
    sessions = (await client.get(f"{URL}/sessions", headers=bearer(a))).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
