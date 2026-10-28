from fastapi import APIRouter, Depends, Request, Response, status

from mallt.core.config import Settings
from mallt.core.db import SessionDep
from mallt.core.errors import Unauthorized
from mallt.core.logging import get_client_ip
from mallt.modules.iam.customer_auth import CustomerAuthService, CustomerView
from mallt.modules.iam.deps import CustomerId, GoogleDep, KvDep, SettingsDep, SmsDep
from mallt.modules.iam.http import clear_refresh_cookie, require_csrf, set_refresh_cookie
from mallt.modules.iam.schemas import (
    CustomerMe,
    CustomerUpdate,
    GoogleLogin,
    OtpRequest,
    OtpRequested,
    OtpVerify,
    TokenOut,
)
from mallt.modules.iam.staff_auth import TokenPair

CUSTOMER_COOKIE = "mallt_crt"

customer_router = APIRouter(prefix="/api/v1/auth/customer", tags=["auth"])


def _service(
    session: SessionDep, settings: Settings, kv: KvDep, sms: SmsDep, google: GoogleDep
) -> CustomerAuthService:
    return CustomerAuthService(session, settings, kv, sms, google)


def _tokens(response: Response, settings: Settings, pair: TokenPair) -> TokenOut:
    set_refresh_cookie(
        response, settings, CUSTOMER_COOKIE, pair.refresh_token, settings.customer_refresh_ttl_s
    )
    return TokenOut(access_token=pair.access_token, expires_in=pair.expires_in)


def _me(view: CustomerView) -> CustomerMe:
    return CustomerMe(
        id=view.id,
        phone_masked=view.phone_masked,
        has_phone=view.phone is not None,
        name=view.name,
        email=view.email,
    )


@customer_router.post("/otp/request", status_code=status.HTTP_202_ACCEPTED)
async def customer_request_otp(
    body: OtpRequest,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> OtpRequested:
    ttl = await _service(session, settings, kv, sms, google).request_otp(
        body.phone, ip=get_client_ip()
    )
    return OtpRequested(expires_in=ttl)


@customer_router.post("/otp/verify")
async def customer_verify_otp(
    body: OtpVerify,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> TokenOut:
    pair = await _service(session, settings, kv, sms, google).verify_otp(
        body.phone, body.otp, user_agent=request.headers.get("user-agent"), ip=get_client_ip()
    )
    return _tokens(response, settings, pair)


@customer_router.post("/google")
async def customer_google_login(
    body: GoogleLogin,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> TokenOut:
    pair = await _service(session, settings, kv, sms, google).google_login(
        body.id_token, user_agent=request.headers.get("user-agent"), ip=get_client_ip()
    )
    return _tokens(response, settings, pair)


@customer_router.post("/phone/verify")
async def customer_link_phone(
    body: OtpVerify,
    customer_id: CustomerId,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> TokenOut:
    pair = await _service(session, settings, kv, sms, google).link_phone(
        customer_id,
        body.phone,
        body.otp,
        user_agent=request.headers.get("user-agent"),
        ip=get_client_ip(),
    )
    return _tokens(response, settings, pair)


@customer_router.post("/refresh", dependencies=[Depends(require_csrf)])
async def customer_refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> TokenOut:
    raw = request.cookies.get(CUSTOMER_COOKIE)
    if not raw:
        raise Unauthorized("invalid_refresh", "No session.")
    pair = await _service(session, settings, kv, sms, google).refresh(
        raw, user_agent=request.headers.get("user-agent"), ip=get_client_ip()
    )
    return _tokens(response, settings, pair)


@customer_router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def customer_logout(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> Response:
    await _service(session, settings, kv, sms, google).logout(request.cookies.get(CUSTOMER_COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, settings, CUSTOMER_COOKIE)
    return response


@customer_router.get("/me")
async def customer_me(
    customer_id: CustomerId,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> CustomerMe:
    return _me(await _service(session, settings, kv, sms, google).me(customer_id))


@customer_router.patch("/me")
async def customer_update_me(
    body: CustomerUpdate,
    customer_id: CustomerId,
    session: SessionDep,
    settings: SettingsDep,
    kv: KvDep,
    sms: SmsDep,
    google: GoogleDep,
) -> CustomerMe:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    view = await _service(session, settings, kv, sms, google).update_me(customer_id, changes)
    return _me(view)
