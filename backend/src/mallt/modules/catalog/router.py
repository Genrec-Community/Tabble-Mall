import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from mallt.core.db import SessionDep
from mallt.core.storage import Storage
from mallt.modules.catalog.schemas import (
    AvailabilityUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ImagePresignIn,
    ImagePresignOut,
    ProductIn,
    ProductOut,
    PublicMenuOut,
    PublicStoreCardOut,
    SettingsOut,
    SettingsUpdate,
)
from mallt.modules.catalog.service import CatalogService
from mallt.modules.iam.deps import KvDep, Staff


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


StorageDep = Annotated[Storage, Depends(get_storage)]

router = APIRouter(prefix="/api/v1", tags=["catalog"])
public_router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _svc(session: SessionDep, kv: KvDep, storage: StorageDep) -> CatalogService:
    return CatalogService(session, kv, storage)


Svc = Annotated[CatalogService, Depends(_svc, scope="function")]


# ---- settings & images ----


@router.get("/stores/{store_id}/settings")
async def get_settings(store_id: uuid.UUID, principal: Staff, svc: Svc) -> SettingsOut:
    return await svc.get_settings(principal, store_id)


@router.patch("/stores/{store_id}/settings")
async def update_settings(
    store_id: uuid.UUID, body: SettingsUpdate, principal: Staff, svc: Svc
) -> SettingsOut:
    return await svc.update_settings(principal, store_id, body)


@router.post("/stores/{store_id}/images/presign")
async def presign_image(
    store_id: uuid.UUID, body: ImagePresignIn, principal: Staff, svc: Svc
) -> ImagePresignOut:
    return await svc.presign(principal, store_id, body)


# ---- categories ----


@router.get("/stores/{store_id}/categories")
async def list_categories(store_id: uuid.UUID, principal: Staff, svc: Svc) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c) for c in await svc.list_categories(principal, store_id)]


@router.post("/stores/{store_id}/categories", status_code=status.HTTP_201_CREATED)
async def create_category(
    store_id: uuid.UUID, body: CategoryCreate, principal: Staff, svc: Svc
) -> CategoryOut:
    return CategoryOut.model_validate(await svc.create_category(principal, store_id, body))


@router.patch("/stores/{store_id}/categories/{category_id}")
async def update_category(
    store_id: uuid.UUID, category_id: uuid.UUID, body: CategoryUpdate, principal: Staff, svc: Svc
) -> CategoryOut:
    return CategoryOut.model_validate(
        await svc.update_category(principal, store_id, category_id, body)
    )


@router.delete(
    "/stores/{store_id}/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_category(
    store_id: uuid.UUID, category_id: uuid.UUID, principal: Staff, svc: Svc
) -> Response:
    await svc.delete_category(principal, store_id, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- products ----


@router.get("/stores/{store_id}/products")
async def list_products(store_id: uuid.UUID, principal: Staff, svc: Svc) -> list[ProductOut]:
    return [ProductOut.model_validate(p) for p in await svc.list_products(principal, store_id)]


@router.post("/stores/{store_id}/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    store_id: uuid.UUID, body: ProductIn, principal: Staff, svc: Svc
) -> ProductOut:
    return ProductOut.model_validate(await svc.create_product(principal, store_id, body))


@router.get("/stores/{store_id}/products/{product_id}")
async def get_product(
    store_id: uuid.UUID, product_id: uuid.UUID, principal: Staff, svc: Svc
) -> ProductOut:
    return ProductOut.model_validate(await svc.get_product(principal, store_id, product_id))


@router.put("/stores/{store_id}/products/{product_id}")
async def update_product(
    store_id: uuid.UUID, product_id: uuid.UUID, body: ProductIn, principal: Staff, svc: Svc
) -> ProductOut:
    return ProductOut.model_validate(
        await svc.update_product(principal, store_id, product_id, body)
    )


@router.delete("/stores/{store_id}/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_product(
    store_id: uuid.UUID, product_id: uuid.UUID, principal: Staff, svc: Svc
) -> Response:
    await svc.archive_product(principal, store_id, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/stores/{store_id}/products/{product_id}/availability")
async def set_availability(
    store_id: uuid.UUID, product_id: uuid.UUID, body: AvailabilityUpdate, principal: Staff, svc: Svc
) -> ProductOut:
    return ProductOut.model_validate(
        await svc.set_availability(principal, store_id, product_id, body)
    )


# ---- public ----


@public_router.get("/malls/{mall_slug}/stores")
async def public_stores(mall_slug: str, response: Response, svc: Svc) -> list[PublicStoreCardOut]:
    response.headers["Cache-Control"] = "public, max-age=30"
    return await svc.public_cards(mall_slug)


@public_router.get("/malls/{mall_slug}/stores/{store_slug}/menu")
async def public_menu(
    mall_slug: str, store_slug: str, response: Response, svc: Svc
) -> PublicMenuOut:
    response.headers["Cache-Control"] = "public, max-age=30"
    return await svc.public_menu(mall_slug, store_slug)
