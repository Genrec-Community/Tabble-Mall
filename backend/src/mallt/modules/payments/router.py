import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from mallt.core.bus import Bus
from mallt.core.db import SessionDep
from mallt.core.errors import NotFound, Unauthorized
from mallt.modules.iam.deps import KvDep, Staff
from mallt.modules.payments.runner import money_kick
from mallt.modules.payments.schemas import (
    PaymentsOverviewOut,
    PaymentTaskOut,
    PayoutAccountCreate,
    PayoutAccountOut,
    StorePayoutsOut,
    WebhookAckOut,
)
from mallt.modules.payments.service import PaymentsService
from mallt.modules.payments.webhooks import ZohoWebhooks
from mallt.modules.payments.zoho import ZohoPaymentProvider, verify_signature


def _svc(session: SessionDep, kv: KvDep, request: Request) -> PaymentsService:
    return PaymentsService(session, kv, request.app.state.payments, money_kick(request.app))


Svc = Annotated[PaymentsService, Depends(_svc, scope="function")]

router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.get("/stores/{store_id}/payout-account")
async def get_payout_account(store_id: uuid.UUID, principal: Staff, svc: Svc) -> PayoutAccountOut:
    return await svc.get_payout_account(principal, store_id)


@router.put("/stores/{store_id}/payout-account")
async def submit_payout_account(
    store_id: uuid.UUID, body: PayoutAccountCreate, principal: Staff, svc: Svc
) -> PayoutAccountOut:
    return await svc.submit_payout_account(principal, store_id, body)


@router.post("/stores/{store_id}/payout-account/refresh")
async def refresh_payout_account(
    store_id: uuid.UUID, principal: Staff, svc: Svc
) -> PayoutAccountOut:
    return await svc.refresh_payout_account(principal, store_id)


@router.get("/stores/{store_id}/payouts")
async def store_payouts(
    store_id: uuid.UUID,
    principal: Staff,
    svc: Svc,
    cursor: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> StorePayoutsOut:
    return await svc.store_payouts(principal, store_id, cursor, limit)


@router.get("/admin/payments")
async def payments_overview(principal: Staff, svc: Svc) -> PaymentsOverviewOut:
    return await svc.overview(principal)


@router.post("/admin/payments/tasks/{task_id}/retry")
async def retry_payment_task(task_id: uuid.UUID, principal: Staff, svc: Svc) -> PaymentTaskOut:
    return await svc.retry_task(principal, task_id)


@router.post("/payments/zoho/webhook", include_in_schema=False)
async def zoho_webhook(request: Request, session: SessionDep, kv: KvDep) -> WebhookAckOut:
    provider = request.app.state.payments
    if not isinstance(provider, ZohoPaymentProvider):
        raise NotFound("not_found", "Not found.")
    body = await request.body()
    key = request.app.state.settings.zoho_webhook_signing_key
    if not verify_signature(body, request.headers.get("x-zoho-webhook-signature"), key):
        raise Unauthorized("bad_signature", "Signature check failed.")
    try:
        event = json.loads(body)
    except ValueError:
        event = {}
    bus: Bus = request.app.state.bus
    if isinstance(event, dict):
        await ZohoWebhooks(session, kv, bus, provider, money_kick(request.app)).handle(event)
    return WebhookAckOut()
