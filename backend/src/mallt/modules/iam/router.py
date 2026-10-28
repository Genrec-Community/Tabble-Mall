from fastapi import APIRouter, Depends, Request, Response, status

from mallt.core.config import Settings
from mallt.core.db import SessionDep
from mallt.core.errors import Forbidden, Unauthorized
from mallt.core.logging import get_client_ip
from mallt.modules.iam.deps import ClaimsDep, KvDep, SettingsDep, Staff, StaffAny
from mallt.modules.iam.schemas import (
    PasswordChange,
    SessionOut,
    StaffLogin,
    StaffMe,
    TokenOut,
    TotpConfirm,
    TotpSetupOut,
)
from mallt.modules.iam.staff_auth import StaffAuthService, TokenPair

COOKIE_PATH = "/api/v1/auth"
STAFF_COOKIE = "mallt_srt"


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


staff_router = APIRouter(prefix="/api/v1/auth/staff", tags=["auth"])


def _tokens(response: Response, settings: Settings, pair: TokenPair) -> TokenOut:
    set_refresh_cookie(
        response, settings, STAFF_COOKIE, pair.refresh_token, settings.staff_refresh_ttl_s
    )
    return TokenOut(access_token=pair.access_token, expires_in=pair.expires_in)


@staff_router.post("/login")
async def staff_login(
    body: StaffLogin,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> TokenOut:
    pair = await StaffAuthService(session, settings, kv).login(
        body.username,
        body.password,
        body.totp_code,
        user_agent=request.headers.get("user-agent"),
        ip=get_client_ip(),
    )
    return _tokens(response, settings, pair)


@staff_router.post("/refresh", dependencies=[Depends(require_csrf)])
async def staff_refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> TokenOut:
    raw = request.cookies.get(STAFF_COOKIE)
    if not raw:
        raise Unauthorized("invalid_refresh", "No session.")
    pair = await StaffAuthService(session, settings, kv).refresh(
        raw, user_agent=request.headers.get("user-agent"), ip=get_client_ip()
    )
    return _tokens(response, settings, pair)


@staff_router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def staff_logout(
    request: Request, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> Response:
    await StaffAuthService(session, settings, kv).logout(request.cookies.get(STAFF_COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, settings, STAFF_COOKIE)
    return response


@staff_router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def staff_logout_all(
    principal: StaffAny, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> Response:
    await StaffAuthService(session, settings, kv).logout_all(principal.staff_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, settings, STAFF_COOKIE)
    return response


@staff_router.get("/me")
async def staff_me(
    principal: StaffAny, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> StaffMe:
    return await StaffAuthService(session, settings, kv).me(principal)


@staff_router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def staff_change_password(
    body: PasswordChange,
    principal: StaffAny,
    claims: ClaimsDep,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
) -> Response:
    await StaffAuthService(session, settings, kv).change_password(
        principal, claims.sid, body.current_password, body.new_password
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.post("/totp/setup")
async def staff_totp_setup(
    principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> TotpSetupOut:
    secret, uri = await StaffAuthService(session, settings, kv).totp_setup(principal)
    return TotpSetupOut(secret=secret, otpauth_uri=uri)


@staff_router.post("/totp/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def staff_totp_confirm(
    body: TotpConfirm, principal: Staff, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> Response:
    await StaffAuthService(session, settings, kv).totp_confirm(principal, body.code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staff_router.get("/sessions")
async def staff_sessions(
    principal: Staff, claims: ClaimsDep, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> list[SessionOut]:
    infos = await StaffAuthService(session, settings, kv).list_sessions(principal.staff_id)
    return [
        SessionOut(
            id=i.id,
            created_at=i.created_at,
            last_seen_at=i.last_seen_at,
            user_agent=i.user_agent,
            ip=i.ip,
            current=i.id == claims.sid,
        )
        for i in infos
    ]
