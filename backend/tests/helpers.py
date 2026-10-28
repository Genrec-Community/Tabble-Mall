"""HTTP helpers for tests: sign staff in and call the API as them."""

import httpx
import pyotp

from tests.factories import DEFAULT_PASSWORD

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
