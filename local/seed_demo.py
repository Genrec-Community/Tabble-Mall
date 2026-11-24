"""Fill a local MallT with the demo mall, its restaurants, menus and photos, and keep it current.

local/run_local.py calls this once the API is up. A fresh install gets the first Platform Admin
from the real seed command; everything else goes through the public HTTP API, exactly as people
would do it in the dashboards. The restaurants and dishes come from demo_menu.py.

The demo carries a version (DEMO_VERSION, stored in local/data/demo-version). When an older
install starts with newer code, it signs in as the demo organization owner and brings the demo up
to date in place: missing restaurants and dishes are added, the existing ones get their new
descriptions, prices and photos. Nothing a person added themselves is removed.

Photos: the files in local/demo-media/ are copied into local/data/media/ under each store's own
key prefix (the API checks it), and the local proxy serves them at /media/.
"""

import asyncio
import json
import secrets
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pyotp

from demo_menu import STORES
from mallt.cli import run_seed_admin
from mallt.core.config import get_settings
from mallt.core.errors import Conflict

API = "http://127.0.0.1:8000/api/v1"
PASSWORD = "MallT-demo-2026"
ADMIN = "admin"
# The platform owner's own super-admin account (above every mall, restaurant and counter login).
OWNER_ADMIN = "jaisamyukth@gmail.com"
ORG_OWNER = "demo.owner"
ORG_SLUG = "demo-foods"
MALL_SLUG = "demo-mall"
DEMO_VERSION = 4  # bump whenever demo_menu.py, the photos or the demo offers change

LOCAL = Path(__file__).resolve().parent
ROOT = LOCAL.parent
LOGINS = ROOT / "demo-logins.txt"
OWNER_LOGIN = ROOT / "owner-login.txt"  # this computer only; never committed
VERSION_FILE = LOCAL / "data" / "demo-version"
PHOTOS = LOCAL / "demo-media" / "dishes"
MEDIA = LOCAL / "data" / "media"  # served by run_local's proxy at /media/


class ApiFailed(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"{status} {body[:300]}")
        self.status = status


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
        raise ApiFailed(exc.code, f"{method} {path}: {exc.read().decode()}") from exc


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


# ---- photos ----


def place_photo(store: dict[str, Any], photo: str) -> str | None:
    """Copies a bundled photo under the store's key prefix; returns its key, or None if absent."""
    src = PHOTOS / f"{photo}.jpg"
    if not src.exists():
        return None
    key = f"org/{store['organization_id']}/store/{store['id']}/demo/{photo}.jpg"
    dest = MEDIA / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return key


def place_logo(store: dict[str, Any], name: str, accent: str) -> str:
    """A round monogram in the restaurant's colour, drawn as SVG (no image files needed)."""
    words = [w for w in name.replace("&", " ").split() if w[:1].isalpha()]
    letters = "".join(w[0] for w in words[:2]).upper() or name[:1].upper()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
        f'<circle cx="80" cy="80" r="80" fill="{accent}"/>'
        '<circle cx="80" cy="80" r="70" fill="none" stroke="#fff" stroke-opacity=".35" '
        'stroke-width="3"/>'
        '<text x="80" y="80" dy=".35em" text-anchor="middle" fill="#fff" '
        "font-family=\"Montserrat,'Segoe UI',Arial,sans-serif\" font-weight="
        f'"800" font-size="{64 if len(letters) > 1 else 80}">{letters}</text></svg>'
    )
    key = f"org/{store['organization_id']}/store/{store['id']}/demo/logo.svg"
    dest = MEDIA / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(svg, encoding="utf-8")
    return key


# ---- menu ----


def product_body(
    dish: tuple[Any, ...],
    category_id: str,
    pos: int,
    image_key: str | None,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """The full ProductIn for a dish. On an update the demo owns only its name, text, prices,
    photo and listed sizes and add-ons: everything else a person set (tax, stock mode, allergens,
    time windows, extra sizes or add-on groups) is kept, and existing sizes and add-ons keep their
    ids (matched by name), so carts and past orders that point at them stay valid."""
    name, diet, description, prep, sizes, group, _photo = dish
    old = existing or {}
    old_variants = {v["name"]: v for v in old.get("variants", [])}
    old_groups = {g["name"]: g for g in old.get("option_groups", [])}

    def variant(n: str, price: int | None, v: dict[str, Any] | None) -> dict[str, Any]:
        out: dict[str, Any] = {"id": v and v["id"], "name": n}
        out["price_paise"] = price if price is not None else (v or {})["price_paise"]
        if v and v.get("stock_count") is not None:
            out["stock_count"] = v["stock_count"]
        return out

    def option_group(g: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": g["id"],
            "name": g["name"],
            "min_select": g["min_select"],
            "max_select": g["max_select"],
            "options": [
                {"id": o["id"], "name": o["name"], "price_delta_paise": o["price_delta_paise"]}
                for o in g["options"]
            ],
        }

    listed = {n for n, _ in sizes}
    variants = [variant(n, p, old_variants.get(n)) for n, p in sizes]
    variants += [variant(n, None, v) for n, v in old_variants.items() if n not in listed]
    groups = []
    if group:
        gname, options = group
        g_old = old_groups.get(gname)
        old_options = {o["name"]: o["id"] for o in (g_old or {}).get("options", [])}
        groups.append(
            {
                "id": g_old["id"] if g_old else None,
                "name": gname,
                "min_select": 0,
                "max_select": len(options),
                "options": [
                    {"id": old_options.get(n), "name": n, "price_delta_paise": p}
                    for n, p in options
                ],
            }
        )
    groups += [option_group(g) for n, g in old_groups.items() if not group or n != group[0]]

    body: dict[str, Any] = {
        key: old[key] for key in ("allergens", "tax_bps", "stock_mode", "windows") if key in old
    }
    body.update(
        name=name,
        diet=diet,
        description=description,
        prep_minutes=prep,
        category_id=category_id,
        position=pos,
        image_key=image_key if image_key else old.get("image_key"),
        variants=variants,
        option_groups=groups,
    )
    return body


def sync_store(
    token: str, mall_id: str, existing: dict[str, dict[str, Any]], spec: dict[str, Any]
) -> bool:
    """Creates or updates one restaurant. Returns True when its owner login was just created."""
    created_owner = False
    store = existing.get(spec["slug"])
    if store is None:
        store = call(
            "POST",
            f"/malls/{mall_id}/stores",
            token,
            {"name": spec["name"], "slug": spec["slug"], "description": spec["description"]},
        )
        try:
            made = call(
                "POST",
                f"/stores/{store['id']}/staff",
                token,
                {
                    "username": spec["owner"],
                    "display_name": f"{spec['name']} owner",
                    "role_key": "store_owner",
                },
            )
            set_password(spec["owner"], made["temp_password"])
            created_owner = True
        except ApiFailed as exc:
            print(f"  could not add the login {spec['owner']}: {exc}")
    else:
        call(
            "PATCH",
            f"/stores/{store['id']}",
            token,
            {"name": spec["name"], "description": spec["description"]},
        )
    sid = store["id"]

    settings: dict[str, Any] = {
        "food_types": spec["food_types"],
        "logo_key": place_logo(store, spec["name"], spec["accent"]),
        "pickup_point": spec.get("pickup_point"),
    }
    banner = place_photo(store, spec["banner"])
    if banner:
        settings["banner_key"] = banner
    call("PATCH", f"/stores/{sid}/settings", token, settings)

    categories = {c["name"]: c for c in call("GET", f"/stores/{sid}/categories", token)}
    products = {p["name"]: p for p in call("GET", f"/stores/{sid}/products", token)}
    for c_pos, (cname, dishes) in enumerate(spec["menu"].items()):
        cat = categories.get(cname)
        if cat is None:
            cat = call(
                "POST", f"/stores/{sid}/categories", token, {"name": cname, "position": c_pos}
            )
        elif cat["position"] != c_pos:
            call(
                "PATCH",
                f"/stores/{sid}/categories/{cat['id']}",
                token,
                {"name": cname, "position": c_pos},
            )
        for p_pos, dish in enumerate(dishes):
            image = place_photo(store, dish[6])
            old = products.get(dish[0])
            body = product_body(dish, cat["id"], p_pos, image, old)
            if old is None:
                call("POST", f"/stores/{sid}/products", token, body)
            else:
                call("PUT", f"/stores/{sid}/products/{old['id']}", token, body)
    return created_owner


# A few running offers, so the mall page, menus and cart show how they work. Each store pays for
# its own (it comes out of its share); MallT takes nothing.
DEMO_OFFERS: dict[str, list[dict[str, Any]]] = {
    "madras-tiffin": [
        {"title": "Breakfast special", "kind": "percent", "value": 1000, "max_discount_paise": 4000}
    ],
    "biryani-darbar": [
        {"title": "Feast deal", "kind": "flat", "value": 5000, "min_subtotal_paise": 39900}
    ],
    "chai-point": [
        {
            "title": "First chai on us",
            "kind": "flat",
            "value": 3000,
            "min_subtotal_paise": 9900,
            "code": "CHAI30",
            "per_customer_limit": 1,
        }
    ],
    "scoops-shakes": [
        {
            "title": "Sweet tooth",
            "kind": "percent",
            "value": 2000,
            "max_discount_paise": 6000,
            "min_subtotal_paise": 19900,
        }
    ],
}
# Mall-wide combos: (name, description, [(store slug, dish)], rupees off the dishes bought alone).
DEMO_COMBOS: list[tuple[str, str, list[tuple[str, str]], int]] = [
    (
        "Burger and shake",
        "A Cheese Burger from Burger Hub with a Mango Shake from Scoops & Shakes.",
        [("burger-hub", "Cheese Burger"), ("scoops-shakes", "Mango Shake")],
        40,
    ),
    (
        "Biryani and kulfi",
        "Chicken Dum Biryani with a Kulfi to finish.",
        [("biryani-darbar", "Chicken Dum Biryani"), ("scoops-shakes", "Kulfi")],
        30,
    ),
]


def sync_offers(owner: str, mall_id: str) -> None:
    """Adds the demo offers and combos that are missing (by name); never touches anything else."""
    stores = {s["slug"]: s for s in call("GET", f"/malls/{mall_id}/stores", owner)}
    products: dict[tuple[str, str], dict[str, Any]] = {}
    for slug, store in stores.items():
        for p in call("GET", f"/stores/{store['id']}/products", owner):
            products[(slug, p["name"])] = p
    for slug, offers in DEMO_OFFERS.items():
        store = stores.get(slug)
        if store is None:
            continue
        have = {o["title"] for o in call("GET", f"/stores/{store['id']}/offers", owner)}
        for offer in offers:
            if offer["title"] not in have:
                call("POST", f"/stores/{store['id']}/offers", owner, offer)
    have = {c["name"] for c in call("GET", f"/malls/{mall_id}/combos", owner)}
    for name, description, dishes, off_rupees in DEMO_COMBOS:
        picked = [products.get(d) for d in dishes]
        if name in have or any(p is None for p in picked):
            continue
        regular = sum(min(v["price_paise"] for v in p["variants"]) for p in picked if p)
        call(
            "POST",
            f"/malls/{mall_id}/combos",
            owner,
            {
                "name": name,
                "description": description,
                "price_paise": regular - off_rupees * 100,
                "items": [{"product_id": p["id"], "quantity": 1} for p in picked if p],
            },
        )


def sync_demo(owner: str, mall_id: str) -> None:
    existing = {s["slug"]: s for s in call("GET", f"/malls/{mall_id}/stores", owner)}
    for spec in STORES:
        print(f"  {spec['name']}")
        sync_store(owner, mall_id, existing, spec)
    print("  offers and combos")
    sync_offers(owner, mall_id)


def find_mall(owner: str) -> str | None:
    for org in call("GET", "/orgs", owner)["items"]:
        for mall in call("GET", f"/orgs/{org['id']}/malls", owner):
            if mall["slug"] == MALL_SLUG:
                return str(mall["id"])
    return None


def installed_version() -> int:
    try:
        return int(VERSION_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 1  # set up before versions were tracked


def write_logins(secret: str | None, uri: str | None) -> None:
    lines = [
        "MallT demo logins (local only). Every staff password: " + PASSWORD,
        "",
        "Customer QR page:   http://localhost:8080/m/" + MALL_SLUG,
        "  Sign in with any 10-digit mobile number. The code is printed by show-otp.bat.",
        "  Burger Hub and Chai Kadai wait for you to accept orders in their dashboards;",
        "  the other restaurants' kitchens run on their own so you can watch an order go live.",
        "  Offers are running at four restaurants (try the coupon CHAI30 at Chai Kadai), and two",
        "  combos apply in the cart by themselves. Rate an order after pickup to see reviews.",
        "",
        "Staff sign-in:      http://localhost:8080/login",
        f"  {ORG_OWNER:<16} organization owner (all restaurants, malls and staff)",
        *[f"  {s['owner']:<16} store owner of {s['name']}" for s in STORES],
    ]
    if secret and uri:
        lines += [
            f"  {ADMIN:<16} platform admin; also needs a 6-digit code from an authenticator app.",
            "                   Add this key to Google Authenticator / Authy (enter key manually):",
            f"                   {secret}",
            f"                   or open: {uri}",
        ]
    elif LOGINS.exists():
        # Keep the admin's authenticator key from the first run; it cannot be shown again.
        old = LOGINS.read_text(encoding="utf-8").splitlines()
        start = next((i for i, ln in enumerate(old) if ln.strip().startswith(ADMIN + " ")), None)
        if start is not None:
            lines += old[start:]
    LOGINS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def ensure_owner_admin() -> None:
    """Create the owner's super-admin once, with a password and authenticator key made on this
    computer, and keep them in owner-login.txt (the only place they are ever written)."""
    if OWNER_LOGIN.exists():
        return
    password = "MallT-" + secrets.token_urlsafe(12)
    try:
        uri = asyncio.run(run_seed_admin(get_settings(), OWNER_ADMIN, "Samyukth", password))
    except Conflict:
        print(f"  {OWNER_ADMIN} already exists; its password is the one you set.")
        return
    secret = pyotp.parse_uri(uri).secret
    text = "\n".join(
        [
            "MallT owner login (this computer only). Keep this file private.",
            "",
            "Sign in at:     http://localhost:8080/login",
            f"Username:       {OWNER_ADMIN}",
            f"Password:       {password}",
            "Authenticator:  add this key to Google Authenticator or Authy (enter key manually):",
            f"                {secret}",
            f"                or open: {uri}",
            "",
            "Change the password any time: sign in, then 'Change password' at the top.",
            "",
        ]
    )
    OWNER_LOGIN.write_text(text, encoding="utf-8")
    print(text)


def main() -> int:
    ensure_owner_admin()
    try:
        uri = asyncio.run(run_seed_admin(get_settings(), ADMIN, "Platform Admin", PASSWORD))
    except Conflict:
        if installed_version() >= DEMO_VERSION:
            print("  the demo is already set up; logins are in demo-logins.txt")
            return 0
        print("  updating the demo restaurants, menus and photos...")
        try:
            owner = login(ORG_OWNER, PASSWORD)
        except ApiFailed:
            print(f"  skipped: {ORG_OWNER}'s password was changed, so the demo cannot be updated.")
            return 0
        mall_id = find_mall(owner)
        if mall_id is None:
            print(f"  skipped: the {MALL_SLUG} mall is gone.")
            return 0
        try:
            sync_demo(owner, mall_id)
        except ApiFailed as exc:  # the old demo still works; try again on the next start
            print(f"  the update stopped part way ({exc}); it will be tried again next start.")
            return 0
        VERSION_FILE.write_text(f"{DEMO_VERSION}\n", encoding="utf-8")
        write_logins(None, None)
        return 0

    secret = pyotp.parse_uri(uri).secret
    admin = login(ADMIN, PASSWORD, secret)
    org = call(
        "POST",
        "/orgs",
        admin,
        {
            "name": "Demo Foods",
            "slug": ORG_SLUG,
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
    try:
        sync_demo(owner, mall["id"])
    except ApiFailed as exc:
        raise SystemExit(f"setting up the demo failed: {exc}") from exc
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(f"{DEMO_VERSION}\n", encoding="utf-8")
    write_logins(secret, uri)
    return 0


if __name__ == "__main__":
    sys.exit(main())
