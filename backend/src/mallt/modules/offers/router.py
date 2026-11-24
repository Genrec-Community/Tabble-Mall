import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from mallt.core.db import SessionDep
from mallt.modules.iam.deps import KvDep, Staff
from mallt.modules.offers.schemas import (
    ComboCreate,
    ComboOut,
    ComboUpdate,
    OfferActiveUpdate,
    OfferCreate,
    OfferOut,
    OfferUpdate,
    PublicOffersOut,
)
from mallt.modules.offers.service import OffersService

router = APIRouter(prefix="/api/v1", tags=["offers"])
public_router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _svc(session: SessionDep, kv: KvDep) -> OffersService:
    return OffersService(session, kv)


Svc = Annotated[OffersService, Depends(_svc, scope="function")]


# ---- store offers and coupons ----


@router.get("/stores/{store_id}/offers")
async def list_offers(store_id: uuid.UUID, principal: Staff, svc: Svc) -> list[OfferOut]:
    return await svc.list_offers(principal, store_id)


@router.post("/stores/{store_id}/offers", status_code=status.HTTP_201_CREATED)
async def create_offer(
    store_id: uuid.UUID, body: OfferCreate, principal: Staff, svc: Svc
) -> OfferOut:
    return await svc.create_offer(principal, store_id, body)


@router.put("/stores/{store_id}/offers/{offer_id}")
async def update_offer(
    store_id: uuid.UUID, offer_id: uuid.UUID, body: OfferUpdate, principal: Staff, svc: Svc
) -> OfferOut:
    return await svc.update_offer(principal, store_id, offer_id, body)


@router.patch("/stores/{store_id}/offers/{offer_id}/active")
async def set_offer_active(
    store_id: uuid.UUID, offer_id: uuid.UUID, body: OfferActiveUpdate, principal: Staff, svc: Svc
) -> OfferOut:
    return await svc.set_offer_active(principal, store_id, offer_id, body.is_active)


@router.delete("/stores/{store_id}/offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_offer(
    store_id: uuid.UUID, offer_id: uuid.UUID, principal: Staff, svc: Svc
) -> Response:
    await svc.delete_offer(principal, store_id, offer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- mall-wide combos ----


@router.get("/malls/{mall_id}/combos")
async def list_combos(mall_id: uuid.UUID, principal: Staff, svc: Svc) -> list[ComboOut]:
    return await svc.list_combos(principal, mall_id)


@router.post("/malls/{mall_id}/combos", status_code=status.HTTP_201_CREATED)
async def create_combo(
    mall_id: uuid.UUID, body: ComboCreate, principal: Staff, svc: Svc
) -> ComboOut:
    return await svc.create_combo(principal, mall_id, body)


@router.put("/malls/{mall_id}/combos/{combo_id}")
async def update_combo(
    mall_id: uuid.UUID, combo_id: uuid.UUID, body: ComboUpdate, principal: Staff, svc: Svc
) -> ComboOut:
    return await svc.update_combo(principal, mall_id, combo_id, body)


@router.patch("/malls/{mall_id}/combos/{combo_id}/active")
async def set_combo_active(
    mall_id: uuid.UUID, combo_id: uuid.UUID, body: OfferActiveUpdate, principal: Staff, svc: Svc
) -> ComboOut:
    return await svc.set_combo_active(principal, mall_id, combo_id, body.is_active)


@router.delete("/malls/{mall_id}/combos/{combo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_combo(
    mall_id: uuid.UUID, combo_id: uuid.UUID, principal: Staff, svc: Svc
) -> Response:
    await svc.delete_combo(principal, mall_id, combo_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- public ----


@public_router.get("/malls/{mall_slug}/offers")
async def public_offers(mall_slug: str, response: Response, svc: Svc) -> PublicOffersOut:
    """Live offers, coupons and combos in a mall, for the mall page and cart."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return await svc.public(mall_slug)
