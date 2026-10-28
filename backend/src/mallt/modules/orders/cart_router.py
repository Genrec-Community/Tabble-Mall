import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from mallt.core.db import SessionDep
from mallt.modules.iam.deps import CustomerId, KvDep
from mallt.modules.orders.cart import CartService
from mallt.modules.orders.schemas import CartLineIn, CartLineUpdate, CartOut

router = APIRouter(prefix="/api/v1/malls/{mall_slug}/cart", tags=["cart"])


def _svc(session: SessionDep, kv: KvDep) -> CartService:
    return CartService(session, kv)


Svc = Annotated[CartService, Depends(_svc, scope="function")]


@router.get("")
async def get_cart(mall_slug: str, customer_id: CustomerId, svc: Svc) -> CartOut:
    return await svc.view(customer_id, mall_slug)


@router.post("/lines", status_code=status.HTTP_201_CREATED)
async def add_line(mall_slug: str, body: CartLineIn, customer_id: CustomerId, svc: Svc) -> CartOut:
    return await svc.add_line(customer_id, mall_slug, body)


@router.patch("/lines/{line_id}")
async def update_line(
    mall_slug: str, line_id: uuid.UUID, body: CartLineUpdate, customer_id: CustomerId, svc: Svc
) -> CartOut:
    return await svc.update_line(customer_id, mall_slug, line_id, body)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(mall_slug: str, customer_id: CustomerId, svc: Svc) -> Response:
    await svc.clear(customer_id, mall_slug)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
