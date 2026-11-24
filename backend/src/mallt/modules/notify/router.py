from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from mallt.core.db import SessionDep
from mallt.modules.iam.deps import CustomerId
from mallt.modules.notify.schemas import (
    NotifyConfigOut,
    NotifyPrefsOut,
    NotifyPrefsUpdate,
    PushSubscriptionIn,
    PushUnsubscribeIn,
)
from mallt.modules.notify.service import NotifyService

router = APIRouter(prefix="/api/v1/notify", tags=["notify"])


def _svc(session: SessionDep, request: Request) -> NotifyService:
    return NotifyService(session, request.app.state.notify)


Svc = Annotated[NotifyService, Depends(_svc, scope="function")]


@router.get("/config")
async def notify_config(svc: Svc) -> NotifyConfigOut:
    """Public: the push key the browser subscribes with, and whether WhatsApp is offered."""
    return await svc.public_config()


@router.post("/push", status_code=status.HTTP_204_NO_CONTENT)
async def push_subscribe(body: PushSubscriptionIn, customer_id: CustomerId, svc: Svc) -> Response:
    await svc.subscribe(customer_id, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/push/remove", status_code=status.HTTP_204_NO_CONTENT)
async def push_unsubscribe(body: PushUnsubscribeIn, customer_id: CustomerId, svc: Svc) -> Response:
    await svc.unsubscribe(customer_id, body.endpoint)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/prefs")
async def get_notify_prefs(customer_id: CustomerId, svc: Svc) -> NotifyPrefsOut:
    return await svc.prefs(customer_id)


@router.put("/prefs")
async def set_notify_prefs(
    body: NotifyPrefsUpdate, customer_id: CustomerId, svc: Svc
) -> NotifyPrefsOut:
    return await svc.set_prefs(customer_id, body.whatsapp)
