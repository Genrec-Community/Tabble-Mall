"""HTTP helpers for tests: sign staff in and call the API as them."""

import httpx
import pyotp

from tests.factories import DEFAULT_PASSWORD, FakeSms

STAFF = "/api/v1/auth/staff"


async def staff_headers(
    client: httpx.AsyncClient,
    username: str,
    *,
    password: str = DEFAULT_PASSWORD,
    totp_secret: str | None = None,
) -> dict[str, str]:
    """Log a staff member in and return their Authorization header."""
    body = {"username": username, "password": password}
    if totp_secret:
        body["totp_code"] = pyotp.TOTP(totp_secret).now()
    r = await client.post(f"{STAFF}/login", json=body)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def customer_headers(client: httpx.AsyncClient, sms: FakeSms, phone: str) -> dict[str, str]:
    """Sign a customer in by phone OTP and return their Authorization header."""
    base = "/api/v1/auth/customer"
    assert (await client.post(f"{base}/otp/request", json={"phone": phone})).status_code == 202
    r = await client.post(f"{base}/otp/verify", json={"phone": phone, "otp": sms.last_otp(phone)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
