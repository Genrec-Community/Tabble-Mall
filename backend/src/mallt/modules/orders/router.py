import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import BaseModel

from mallt.core.bus import Bus
from mallt.core.db import SessionDep
from mallt.core.errors import BadRequest
from mallt.core.pagination import Page
from mallt.core.rbac import P
from mallt.modules.iam.deps import CustomerId, KvDep, Staff
from mallt.modules.orders.enums import StoreOrderStatus as S
from mallt.modules.orders.schemas import (
    CheckoutIn,
    CustomerOrderOut,
    PickupIn,
    ReasonIn,
    StoreOrderOut,
)
from mallt.modules.orders.service import OrderService
from mallt.modules.payments.provider import PaymentProvider
from mallt.modules.printing.schemas import ReprintIn


def _svc(session: SessionDep, kv: KvDep, request: Request) -> OrderService:
    bus: Bus = request.app.state.bus
    payments: PaymentProvider = request.app.state.payments
    return OrderService(session, kv, bus, payments)


Svc = Annotated[OrderService, Depends(_svc, scope="function")]
Limit = Annotated[int, Query(ge=1, le=100)]
View = Annotated[str, Query(pattern="^(active|history|all)$")]

customer_router = APIRouter(prefix="/api/v1", tags=["orders"])
store_router = APIRouter(prefix="/api/v1", tags=["store-orders"])


# ---- customer ----


@customer_router.post("/malls/{mall_slug}/checkout")
async def checkout(
    mall_slug: str,
    body: CheckoutIn,
    customer_id: CustomerId,
    svc: Svc,
    response: Response,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> CustomerOrderOut:
    if not idempotency_key:
        raise BadRequest("idempotency_key_required", "Send an Idempotency-Key header.")
    order, created = await svc.checkout(customer_id, mall_slug, idempotency_key, body.note)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return order


@customer_router.get("/orders")
async def list_my_orders(
    customer_id: CustomerId, svc: Svc, before: uuid.UUID | None = None, limit: Limit = 20
) -> Page[CustomerOrderOut]:
    return await svc.list_customer_orders(customer_id, before, limit)


@customer_router.get("/orders/{order_id}")
async def get_my_order(order_id: uuid.UUID, customer_id: CustomerId, svc: Svc) -> CustomerOrderOut:
    return await svc.get_customer_order(customer_id, order_id)


@customer_router.post("/orders/stores/{store_order_id}/cancel")
async def cancel_my_order(
    store_order_id: uuid.UUID, customer_id: CustomerId, svc: Svc
) -> CustomerOrderOut:
    return await svc.customer_cancel(customer_id, store_order_id)


# ---- staff ----


@store_router.get("/stores/{store_id}/orders")
async def list_store_orders(
    store_id: uuid.UUID,
    principal: Staff,
    svc: Svc,
    view: View = "all",
    before: uuid.UUID | None = None,
    limit: Limit = 50,
) -> Page[StoreOrderOut]:
    return await svc.list_store_orders(principal, store_id, view, before, limit)


@store_router.get("/stores/{store_id}/orders/{order_id}")
async def get_store_order(
    store_id: uuid.UUID, order_id: uuid.UUID, principal: Staff, svc: Svc
) -> StoreOrderOut:
    return await svc.get_store_order(principal, store_id, order_id)


def _step(name: str, to: S) -> None:
    async def handler(
        store_id: uuid.UUID, order_id: uuid.UUID, principal: Staff, svc: Svc
    ) -> StoreOrderOut:
        return await svc.advance(principal, store_id, order_id, to)

    handler.__name__ = name
    store_router.post(f"/stores/{{store_id}}/orders/{{order_id}}/{name}")(handler)


_step("accept", S.ACCEPTED)
_step("preparing", S.PREPARING)
_step("ready", S.READY)


@store_router.post("/stores/{store_id}/orders/{order_id}/reject")
async def reject_order(
    store_id: uuid.UUID, order_id: uuid.UUID, body: ReasonIn, principal: Staff, svc: Svc
) -> StoreOrderOut:
    return await svc.advance(principal, store_id, order_id, S.REJECTED, reason=body.reason)


@store_router.post("/stores/{store_id}/orders/{order_id}/cancel")
async def cancel_order(
    store_id: uuid.UUID, order_id: uuid.UUID, body: ReasonIn, principal: Staff, svc: Svc
) -> StoreOrderOut:
    return await svc.advance(
        principal,
        store_id,
        order_id,
        S.CANCELLED,
        reason=body.reason,
        permission=P.STORE_ORDER_CANCEL,
    )


@store_router.post("/stores/{store_id}/orders/{order_id}/pickup")
async def verify_pickup(
    store_id: uuid.UUID, order_id: uuid.UUID, body: PickupIn, principal: Staff, svc: Svc
) -> StoreOrderOut:
    return await svc.verify_pickup(principal, store_id, order_id, body.code)


@store_router.get("/orgs/{org_id}/orders")
async def list_org_orders(
    org_id: uuid.UUID,
    principal: Staff,
    svc: Svc,
    view: View = "all",
    before: uuid.UUID | None = None,
    limit: Limit = 50,
) -> Page[StoreOrderOut]:
    return await svc.list_org_orders(principal, org_id, view, before, limit)


@store_router.get("/malls/{mall_id}/orders")
async def list_mall_orders(
    mall_id: uuid.UUID,
    principal: Staff,
    svc: Svc,
    view: View = "all",
    before: uuid.UUID | None = None,
    limit: Limit = 50,
) -> Page[StoreOrderOut]:
    return await svc.list_mall_orders(principal, mall_id, view, before, limit)


class ReprintOut(BaseModel):
    queued: int


@store_router.post(
    "/stores/{store_id}/orders/{order_id}/print", status_code=status.HTTP_202_ACCEPTED
)
async def reprint_order(
    store_id: uuid.UUID, order_id: uuid.UUID, body: ReprintIn, principal: Staff, svc: Svc
) -> ReprintOut:
    return ReprintOut(queued=await svc.reprint(principal, store_id, order_id, body.what))
