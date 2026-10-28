from typing import Annotated

from fastapi import Depends, Request

from mallt.core.config import Settings
from mallt.core.db import SessionDep
from mallt.core.errors import Forbidden, Unauthorized
from mallt.core.kv import KV, get_kv
from mallt.core.security import AccessClaims, decode_access_token
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.sessions import SessionService


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
KvDep = Annotated[KV, Depends(get_kv)]


def bearer_claims(request: Request, settings: SettingsDep) -> AccessClaims:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("invalid_token", "Missing bearer token.")
    return decode_access_token(settings, token)


ClaimsDep = Annotated[AccessClaims, Depends(bearer_claims)]


async def _staff_principal(
    claims: AccessClaims, session: SessionDep, settings: Settings, kv: KV
) -> Principal:
    if claims.typ != "staff":
        raise Unauthorized("invalid_token", "Invalid or expired access token.")
    if not await SessionService(session, settings, kv).is_active(claims.sid):
        raise Unauthorized("invalid_token", "This session has ended.")
    return await AuthzService(session, kv).load_principal(claims.sub)


async def current_staff_any(
    claims: ClaimsDep, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> Principal:
    """The signed-in staff member, even if they still must change their password."""
    return await _staff_principal(claims, session, settings, kv)


async def current_staff(
    claims: ClaimsDep, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> Principal:
    principal = await _staff_principal(claims, session, settings, kv)
    if principal.must_change_password:
        raise Forbidden("password_change_required", "Change your password to continue.")
    return principal


# scope="function": these use the request's DB session, which commits right after the handler.
StaffAny = Annotated[Principal, Depends(current_staff_any, scope="function")]
Staff = Annotated[Principal, Depends(current_staff, scope="function")]
