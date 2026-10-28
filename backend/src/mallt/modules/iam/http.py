from fastapi import Request, Response

from mallt.core.config import Settings
from mallt.core.errors import Forbidden

COOKIE_PATH = "/api/v1/auth"


def require_csrf(request: Request) -> None:
    """Cookie-authenticated endpoints need a header a cross-site form cannot send."""
    if request.headers.get("x-requested-with") != "mallt":
        raise Forbidden("csrf", "Missing X-Requested-With header.")


def set_refresh_cookie(
    response: Response, settings: Settings, name: str, value: str, max_age: int
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response, settings: Settings, name: str) -> None:
    response.delete_cookie(
        name, httponly=True, samesite="lax", secure=settings.cookie_secure, path=COOKIE_PATH
    )
