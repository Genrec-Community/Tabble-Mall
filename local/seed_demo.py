"""Fill a fresh local MallT with a demo mall, two food stores and their menus.

local/run_local.py calls this once the API is up. It creates the first Platform Admin with the
real seed command, then sets everything else up through the public HTTP API, exactly as people
would in the dashboards. Running it again does nothing once the demo exists. The logins are
printed and saved to demo-logins.txt next to start.bat.
"""

import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pyotp

from mallt.cli import run_seed_admin
from mallt.core.config import get_settings
from mallt.core.errors import Conflict

API = "http://127.0.0.1:8000/api/v1"
PASSWORD = "MallT-demo-2026"
ADMIN = "admin"
ORG_OWNER = "demo.owner"
MALL_SLUG = "demo-mall"
LOGINS = Path(__file__).resolve().parents[1] / "demo-logins.txt"

STORES: list[dict[str, Any]] = [
    {
        "name": "Burger Hub",
        "slug": "burger-hub",
        "owner": "burger.owner",
        "food_types": ["fast_food"],
        "menu": {
            "Burgers": [
                (
                    "Cheese Burger",
                    "veg",
                    [("Regular", 12000), ("Large", 18000)],
                    ("Extras", [("Extra cheese", 2000), ("Jalapenos", 1500)]),
                ),
                ("Chicken Burger", "nonveg", [("Regular", 15000)], None),
            ],
            "Sides": [("French Fries", "veg", [("Small", 8000), ("Large", 12000)], None)],
        },
    },
    {
        "name": "Chai Point",
        "slug": "chai-point",
        "owner": "chai.owner",
        "food_types": ["beverages", "snacks"],
        "menu": {
            "Drinks": [
                ("Masala Chai", "veg", [("Cup", 3000), ("Flask", 15000)], None),
                (
                    "Cold Coffee",
                    "veg",
                    [("Regular", 9000)],
                    ("Add-ons", [("Ice cream scoop", 3000)]),
                ),
            ],
            "Snacks": [("Samosa", "veg", [("2 pieces", 4000)], None)],
        },
    },
]


def call(method: str, path: str, token: str | None = None, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} failed: {exc.code} {exc.read().decode()[:500]}") from exc


def login(username: str, password: str, totp_secret: str | None = None) -> str:
    body = {"username": username, "password": password}
    if totp_secret:
        body["totp_code"] = pyotp.TOTP(totp_secret).now()
    return str(call("POST", "/auth/staff/login", body=body)["access_token"])


def set_password(username: str, temp_password: str) -> str:
    first = login(username, temp_password)
    call(
        "POST",
        "/auth/staff/password",
        first,
        {"current_password": temp_password, "new_password": PASSWORD},
    )
    return login(username, PASSWORD)


def product(
    name: str, diet: str, sizes: list[tuple[str, int]], group: Any, category_id: str, pos: int
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "diet": diet,
        "category_id": category_id,
        "position": pos,
        "variants": [{"name": n, "price_paise": p} for n, p in sizes],
    }
    if group:
        gname, options = group
        body["option_groups"] = [
            {
                "name": gname,
                "min_select": 0,
                "max_select": len(options),
                "options": [{"name": n, "price_delta_paise": p} for n, p in options],
            }
        ]
    return body


def main() -> int:
    try:
        uri = asyncio.run(run_seed_admin(get_settings(), ADMIN, "Platform Admin", PASSWORD))
    except Conflict:
        print("  the demo is already set up; logins are in demo-logins.txt")
        return 0
    secret = pyotp.parse_uri(uri).secret

    admin = login(ADMIN, PASSWORD, secret)
    org = call(
        "POST",
        "/orgs",
        admin,
        {
            "name": "Demo Foods",
            "slug": "demo-foods",
            "owner": {"username": ORG_OWNER, "display_name": "Demo Owner"},
        },
    )
    owner = set_password(ORG_OWNER, org["temp_password"])
    mall = call(
        "POST",
        f"/orgs/{org['org']['id']}/malls",
        owner,
        {"name": "Demo Mall", "slug": MALL_SLUG, "city": "Chennai"},
    )

    for s in STORES:
        store = call(
            "POST", f"/malls/{mall['id']}/stores", owner, {"name": s["name"], "slug": s["slug"]}
        )
        created = call(
            "POST",
            f"/stores/{store['id']}/staff",
            owner,
            {
                "username": s["owner"],
                "display_name": f"{s['name']} owner",
                "role_key": "store_owner",
            },
        )
        token = set_password(s["owner"], created["temp_password"])
        call("PATCH", f"/stores/{store['id']}/settings", token, {"food_types": s["food_types"]})
        for c_pos, (category, items) in enumerate(s["menu"].items()):
            cat = call(
                "POST",
                f"/stores/{store['id']}/categories",
                token,
                {"name": category, "position": c_pos},
            )
            for p_pos, (name, diet, sizes, group) in enumerate(items):
                call(
                    "POST",
                    f"/stores/{store['id']}/products",
                    token,
                    product(name, diet, sizes, group, cat["id"], p_pos),
                )

    lines = [
        "MallT demo logins (local only). Every staff password: " + PASSWORD,
        "",
        "Customer QR page:   http://localhost:8080/m/" + MALL_SLUG,
        "  Sign in with any 10-digit mobile number. The code is printed by show-otp.bat.",
        "",
        "Staff sign-in:      http://localhost:8080/login",
        f"  {ORG_OWNER:<14} organization owner (all stores, malls and staff)",
        *[f"  {s['owner']:<14} store owner of {s['name']}" for s in STORES],
        f"  {ADMIN:<14} platform admin; also needs a 6-digit code from an authenticator app.",
        "                 Add this key to Google Authenticator / Authy (enter key manually):",
        f"                 {secret}",
        f"                 or open: {uri}",
    ]
    LOGINS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
