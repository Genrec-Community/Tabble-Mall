import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.enums import ActiveStatus
from mallt.core.rbac import Scope
from mallt.modules.iam.customer_auth import generate_otp
from mallt.modules.iam.models import Customer
from tests.factories import DEFAULT_PASSWORD, FakeSms, make_org, make_staff

C = "/api/v1/auth/customer"
STAFF = "/api/v1/auth/staff"
CSRF = {"X-Requested-With": "mallt"}
PHONE = "9361899061"


async def request_otp(client: httpx.AsyncClient, phone: str = PHONE) -> httpx.Response:
    return await client.post(f"{C}/otp/request", json={"phone": phone})


async def sign_in(client: httpx.AsyncClient, sms: FakeSms, phone: str = PHONE) -> httpx.Response:
    assert (await request_otp(client, phone)).status_code == 202
    digits = phone.removeprefix("+91").replace(" ", "")[-10:]
    r = await client.post(f"{C}/otp/verify", json={"phone": phone, "otp": sms.last_otp(digits)})
    assert r.status_code == 200, r.text
    return r


def bearer(r: httpx.Response) -> dict[str, str]:
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def google(
    client: httpx.AsyncClient, sub: str = "g-1", email: str = "a@x.com", name: str = "Asha"
) -> httpx.Response:
    return await client.post(f"{C}/google", json={"id_token": f"good:{sub}|{email}|{name}"})


# ---------- phone OTP ----------


async def test_otp_login_end_to_end(client: httpx.AsyncClient, sms: FakeSms) -> None:
    r = await request_otp(client)
    assert r.status_code == 202 and r.json() == {"expires_in": 300}
    assert PHONE not in r.text and sms.sent[0][0] == PHONE and len(sms.sent[0][1]) == 6

    ok = await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": sms.last_otp(PHONE)})
    assert ok.status_code == 200 and ok.json()["token_type"] == "bearer"
    set_cookie = ok.headers["set-cookie"].lower()
    assert (
        "mallt_crt=" in set_cookie
        and "httponly" in set_cookie
        and "path=/api/v1/auth" in set_cookie
    )

    me = (await client.get(f"{C}/me", headers=bearer(ok))).json()
    assert me["has_phone"] is True and me["phone_masked"] == "******9061"
    assert PHONE not in str(me)


async def test_every_way_of_writing_a_number_is_the_same_customer(
    app: FastAPI, client: httpx.AsyncClient, sms: FakeSms
) -> None:
    ids = set()
    for i, raw in enumerate(["+91 93618 99061", "09361899061", "919361899061", "9361899061"]):
        r = await sign_in(client, sms, raw)
        ids.add((await client.get(f"{C}/me", headers=bearer(r))).json()["id"])
        if i < 3:
            await reset_limits(app)
    assert len(ids) == 1


async def reset_limits(app: FastAPI) -> None:
    """The per-phone send limit is 3 per window; clear counters so a test can go on signing in."""
    await app.state.kv.flush()


@pytest.mark.parametrize("bad", ["12345", "5361899061", "", "abcdefghij"])
async def test_invalid_phone_numbers_are_rejected(
    client: httpx.AsyncClient, sms: FakeSms, bad: str
) -> None:
    r = await request_otp(client, bad)
    assert r.status_code == 422 and sms.sent == []


async def test_send_limit_is_three_per_phone_per_window(
    client: httpx.AsyncClient, sms: FakeSms
) -> None:
    for _ in range(3):
        assert (await request_otp(client)).status_code == 202
    r = await request_otp(client)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert len(sms.sent) == 3
    assert (await request_otp(client, "9876543210")).status_code == 202  # other numbers unaffected


async def test_send_limit_is_twenty_per_ip_per_hour(
    client: httpx.AsyncClient, sms: FakeSms
) -> None:
    for n in range(20):
        assert (await request_otp(client, f"98765432{n:02d}")).status_code == 202
    assert (await request_otp(client, "9999999999")).status_code == 429


async def test_wrong_otp_is_refused_and_five_tries_burn_the_code(
    client: httpx.AsyncClient, sms: FakeSms, app: FastAPI
) -> None:
    await request_otp(client)
    right = sms.last_otp(PHONE)
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        r = await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": wrong})
        assert r.status_code == 401 and r.json()["code"] == "invalid_otp"

    sixth = await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": right})
    assert sixth.status_code == 429 and "Retry-After" in sixth.headers
    assert (
        await app.state.kv.get(f"otp:{PHONE}") is None
    )  # the code is gone, even the right one fails
    again = await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": right})
    assert again.status_code == 429


async def test_expired_or_never_requested_otp_is_refused(
    client: httpx.AsyncClient, sms: FakeSms, app: FastAPI
) -> None:
    r = await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": "123456"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_otp"
    await request_otp(client)
    await app.state.kv.delete(f"otp:{PHONE}")  # what the TTL does after five minutes
    r = await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": sms.last_otp(PHONE)})
    assert r.status_code == 401


async def test_an_otp_works_once(client: httpx.AsyncClient, sms: FakeSms) -> None:
    await request_otp(client)
    otp = sms.last_otp(PHONE)
    assert (
        await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": otp})
    ).status_code == 200
    assert (
        await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": otp})
    ).status_code == 401


async def test_otp_for_one_phone_does_not_work_for_another(
    client: httpx.AsyncClient, sms: FakeSms
) -> None:
    other = "9876543210"
    await request_otp(client, PHONE)
    await request_otp(client, other)
    if sms.last_otp(PHONE) == sms.last_otp(other):
        pytest.skip("two random OTPs collided (1 in a million)")
    r = await client.post(f"{C}/otp/verify", json={"phone": other, "otp": sms.last_otp(PHONE)})
    assert r.status_code == 401


async def test_sms_provider_failure_is_a_502_and_leaves_no_usable_code(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    app.state.sms = FakeSms(fail=True)
    r = await request_otp(client)
    assert r.status_code == 502 and r.json()["code"] == "sms_failed"
    assert await app.state.kv.get(f"otp:{PHONE}") is None


# ---------- Google ----------


async def test_google_login_creates_a_customer_without_a_phone(client: httpx.AsyncClient) -> None:
    first = await google(client)
    me = (await client.get(f"{C}/me", headers=bearer(first))).json()
    assert me["has_phone"] is False and me["phone_masked"] is None
    assert me["email"] == "a@x.com" and me["name"] == "Asha"
    again = await google(client)
    assert (await client.get(f"{C}/me", headers=bearer(again))).json()["id"] == me["id"]


async def test_bad_google_token_is_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{C}/google", json={"id_token": "forged"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_google_token"


# ---------- linking a phone to a Google account ----------


async def test_google_customer_adds_a_new_phone(client: httpx.AsyncClient, sms: FakeSms) -> None:
    g = await google(client)
    await request_otp(client)
    r = await client.post(
        f"{C}/phone/verify", json={"phone": PHONE, "otp": sms.last_otp(PHONE)}, headers=bearer(g)
    )
    assert r.status_code == 200
    me = (await client.get(f"{C}/me", headers=bearer(r))).json()
    assert me["has_phone"] is True and me["email"] == "a@x.com"
    assert (
        await client.get(f"{C}/me", headers=bearer(g))
    ).status_code == 401  # old session replaced


async def test_phone_that_already_has_an_account_absorbs_the_google_identity(
    app: FastAPI, client: httpx.AsyncClient, sms: FakeSms, db_session: AsyncSession
) -> None:
    phone_user = await sign_in(client, sms)
    phone_id = (await client.get(f"{C}/me", headers=bearer(phone_user))).json()["id"]
    await reset_limits(app)

    g = await google(client)
    google_id = (await client.get(f"{C}/me", headers=bearer(g))).json()["id"]
    assert google_id != phone_id
    await request_otp(client)
    r = await client.post(
        f"{C}/phone/verify", json={"phone": PHONE, "otp": sms.last_otp(PHONE)}, headers=bearer(g)
    )
    assert r.status_code == 200
    assert (await client.get(f"{C}/me", headers=bearer(r))).json()["id"] == phone_id

    rows = (await db_session.execute(select(Customer.google_sub, Customer.phone))).all()
    assert rows == [("g-1", PHONE)]  # one account; the phone-less Google duplicate is gone
    again = await google(client)  # signing in with Google now lands on the merged account
    assert (await client.get(f"{C}/me", headers=bearer(again))).json()["id"] == phone_id


async def test_phone_owned_by_a_different_google_account_is_a_conflict(
    app: FastAPI, client: httpx.AsyncClient, sms: FakeSms
) -> None:
    g1 = await google(client, "g-1", "a@x.com")
    await request_otp(client)
    assert (
        await client.post(
            f"{C}/phone/verify",
            json={"phone": PHONE, "otp": sms.last_otp(PHONE)},
            headers=bearer(g1),
        )
    ).status_code == 200
    await reset_limits(app)
    g2 = await google(client, "g-2", "b@x.com")
    await request_otp(client)
    r = await client.post(
        f"{C}/phone/verify", json={"phone": PHONE, "otp": sms.last_otp(PHONE)}, headers=bearer(g2)
    )
    assert r.status_code == 409 and r.json()["code"] == "phone_belongs_to_other_account"


async def test_phone_verify_needs_a_customer_session_and_a_valid_otp(
    client: httpx.AsyncClient, sms: FakeSms
) -> None:
    assert (
        await client.post(f"{C}/phone/verify", json={"phone": PHONE, "otp": "123456"})
    ).status_code == 401
    g = await google(client)
    r = await client.post(
        f"{C}/phone/verify", json={"phone": PHONE, "otp": "123456"}, headers=bearer(g)
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_otp"


# ---------- sessions ----------


async def test_customer_refresh_rotates_and_reuse_revokes_the_family(
    client: httpx.AsyncClient, sms: FakeSms
) -> None:
    first = (await sign_in(client, sms)).cookies["mallt_crt"]
    r2 = await client.post(f"{C}/refresh", headers={**CSRF, "Cookie": f"mallt_crt={first}"})
    assert r2.status_code == 200
    second = r2.cookies["mallt_crt"]
    assert second != first
    replay = await client.post(f"{C}/refresh", headers={**CSRF, "Cookie": f"mallt_crt={first}"})
    assert replay.status_code == 401 and replay.json()["code"] == "refresh_reuse"
    dead = await client.post(f"{C}/refresh", headers={**CSRF, "Cookie": f"mallt_crt={second}"})
    assert dead.status_code == 401
    assert (await client.get(f"{C}/me", headers=bearer(r2))).status_code == 401


async def test_customer_refresh_needs_the_csrf_header(
    client: httpx.AsyncClient, sms: FakeSms
) -> None:
    raw = (await sign_in(client, sms)).cookies["mallt_crt"]
    r = await client.post(f"{C}/refresh", headers={"Cookie": f"mallt_crt={raw}"})
    assert r.status_code == 403 and r.json()["code"] == "csrf"


async def test_customer_logout_ends_the_session(client: httpx.AsyncClient, sms: FakeSms) -> None:
    ok = await sign_in(client, sms)
    raw = ok.cookies["mallt_crt"]
    assert (
        await client.post(f"{C}/logout", headers={**CSRF, "Cookie": f"mallt_crt={raw}"})
    ).status_code == 204
    assert (await client.get(f"{C}/me", headers=bearer(ok))).status_code == 401


async def test_refresh_cookies_are_not_interchangeable_between_identity_types(
    client: httpx.AsyncClient, sms: FakeSms, db_session: AsyncSession
) -> None:
    await make_staff(db_session, "asha")
    staff_raw = (
        await client.post(f"{STAFF}/login", json={"username": "asha", "password": DEFAULT_PASSWORD})
    ).cookies["mallt_srt"]
    customer_raw = (await sign_in(client, sms)).cookies["mallt_crt"]
    as_customer = await client.post(
        f"{C}/refresh", headers={**CSRF, "Cookie": f"mallt_crt={staff_raw}"}
    )
    as_staff = await client.post(
        f"{STAFF}/refresh", headers={**CSRF, "Cookie": f"mallt_srt={customer_raw}"}
    )
    assert as_customer.status_code == 401 and as_staff.status_code == 401


async def test_identity_types_are_not_interchangeable(
    client: httpx.AsyncClient, sms: FakeSms, db_session: AsyncSession
) -> None:
    org = await make_org(db_session)
    await make_staff(db_session, "asha", [("org_manager", Scope.org(org.id))])
    staff = await client.post(
        f"{STAFF}/login", json={"username": "asha", "password": DEFAULT_PASSWORD}
    )
    customer = await sign_in(client, sms)
    assert (await client.get(f"{C}/me", headers=bearer(staff))).status_code == 401
    assert (await client.get(f"{STAFF}/me", headers=bearer(customer))).status_code == 401
    assert (await client.get("/api/v1/roles", headers=bearer(customer))).status_code == 401


async def test_suspended_customers_are_locked_out(
    app: FastAPI, client: httpx.AsyncClient, sms: FakeSms, db_session: AsyncSession
) -> None:
    ok = await sign_in(client, sms)
    raw = ok.cookies["mallt_crt"]
    await db_session.execute(update(Customer).values(status=ActiveStatus.SUSPENDED))
    me = await client.get(f"{C}/me", headers=bearer(ok))
    assert me.status_code == 401 and me.json()["code"] == "account_suspended"
    refresh = await client.post(f"{C}/refresh", headers={**CSRF, "Cookie": f"mallt_crt={raw}"})
    assert refresh.status_code == 401 and refresh.json()["code"] == "account_suspended"
    await reset_limits(app)
    await request_otp(client)
    login = await client.post(f"{C}/otp/verify", json={"phone": PHONE, "otp": sms.last_otp(PHONE)})
    assert login.status_code == 401 and login.json()["code"] == "account_suspended"


# ---------- profile ----------


async def test_profile_can_be_updated(client: httpx.AsyncClient, sms: FakeSms) -> None:
    h = bearer(await sign_in(client, sms))
    r = await client.patch(
        f"{C}/me", json={"name": "Asha K", "email": "asha@example.com"}, headers=h
    )
    assert (
        r.status_code == 200
        and r.json()["name"] == "Asha K"
        and r.json()["email"] == "asha@example.com"
    )
    assert (await client.patch(f"{C}/me", json={"name": "x" * 200}, headers=h)).status_code == 422
    assert (
        await client.patch(f"{C}/me", json={"email": "not-an-email"}, headers=h)
    ).status_code == 422
    assert (await client.patch(f"{C}/me", json={"name": "Only Name"}, headers=h)).json()[
        "email"
    ] == "asha@example.com"


# ---------- fixed OTP for end-to-end tests ----------


def test_fixed_otp_is_honoured_only_in_the_test_environment() -> None:
    fixed = "123456"
    assert generate_otp(Settings(env="test", e2e_fixed_otp=fixed, _env_file=None)) == fixed  # type: ignore[call-arg]
    for env in ("dev", "prod"):
        cfg = Settings(
            env=env,
            e2e_fixed_otp=fixed,
            jwt_secret="x" * 40,
            otp_pepper="y" * 40,
            cookie_secure=True,
            _env_file=None,
        )  # type: ignore[call-arg]
        assert cfg.e2e_fixed_otp == fixed
        got = {generate_otp(cfg) for _ in range(5)}
        assert got != {fixed}
