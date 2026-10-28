import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.db import SessionDep
from mallt.core.enums import ActiveStatus
from mallt.core.errors import Forbidden, Unauthorized
from mallt.core.kv import KV, get_kv
from mallt.core.security import AccessClaims, decode_access_token
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.google import GoogleVerifier
from mallt.modules.iam.repository import CustomerRepository
from mallt.modules.iam.sessions import SessionService
from mallt.modules.iam.sms import SmsSender


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


def get_sms(request: Request) -> SmsSender:
    sender: SmsSender = request.app.state.sms
    return sender


def get_google(request: Request) -> GoogleVerifier:
    verifier: GoogleVerifier = request.app.state.google
    return verifier


SmsDep = Annotated[SmsSender, Depends(get_sms)]
GoogleDep = Annotated[GoogleVerifier, Depends(get_google)]


async def current_customer_id(
    claims: ClaimsDep, session: SessionDep, settings: SettingsDep, kv: KvDep
) -> uuid.UUID:
    """The signed-in customer's id (their account must exist, be active, and the session live)."""
    return await customer_id_for(claims, session, settings, kv)


async def staff_principal_for(
    claims: AccessClaims, session: AsyncSession, settings: Settings, kv: KV
) -> Principal:
    """Same checks as the ``Staff`` dependency, for callers outside an HTTP request (sockets)."""
    principal = await _staff_principal(claims, session, settings, kv)
    if principal.must_change_password:
        raise Forbidden("password_change_required", "Change your password to continue.")
    return principal


async def customer_id_for(
    claims: AccessClaims, session: AsyncSession, settings: Settings, kv: KV
) -> uuid.UUID:
    if claims.typ != "customer":
        raise Unauthorized("invalid_token", "Invalid or expired access token.")
    if not await SessionService(session, settings, kv).is_active(claims.sid):
        raise Unauthorized("invalid_token", "This session has ended.")
    customer = await CustomerRepository(session).get(claims.sub)
    if customer is None:
        raise Unauthorized("invalid_token", "Invalid or expired access token.")
    if customer.status != ActiveStatus.ACTIVE:
        raise Unauthorized("account_suspended", "This account is suspended.")
    return customer.id


CustomerId = Annotated[uuid.UUID, Depends(current_customer_id, scope="function")]
