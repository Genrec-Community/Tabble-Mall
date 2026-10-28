import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from mallt.core.db import SessionDep
from mallt.core.enums import ActiveStatus
from mallt.core.pagination import Page
from mallt.modules.iam.deps import KvDep, Staff
from mallt.modules.tenancy.schemas import (
    MallCreate,
    MallOut,
    MallUpdate,
    OrgCreate,
    OrgCreatedOut,
    OrgOut,
    OrgUpdate,
    PublicMallOut,
    StoreCreate,
    StoreOut,
    StoreUpdate,
)
from mallt.modules.tenancy.service import TenancyService

orgs_router = APIRouter(prefix="/api/v1", tags=["orgs"])
malls_router = APIRouter(prefix="/api/v1", tags=["malls"])
stores_router = APIRouter(prefix="/api/v1", tags=["stores"])
public_router = APIRouter(prefix="/api/v1/public", tags=["public"])

ACTIVE, SUSPENDED = ActiveStatus.ACTIVE, ActiveStatus.SUSPENDED


# ---- organizations ----


@orgs_router.post("/orgs", status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrgCreate, principal: Staff, session: SessionDep, kv: KvDep
) -> OrgCreatedOut:
    return await TenancyService(session, kv).create_org(principal, body)


@orgs_router.get("/orgs")
async def list_orgs(
    principal: Staff,
    session: SessionDep,
    kv: KvDep,
    cursor: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[OrgOut]:
    return await TenancyService(session, kv).list_orgs(principal, cursor, limit)


@orgs_router.get("/orgs/{org_id}")
async def get_org(org_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep) -> OrgOut:
    return OrgOut.model_validate(await TenancyService(session, kv).get_org(principal, org_id))


@orgs_router.patch("/orgs/{org_id}")
async def update_org(
    org_id: uuid.UUID, body: OrgUpdate, principal: Staff, session: SessionDep, kv: KvDep
) -> OrgOut:
    org = await TenancyService(session, kv).update_org(principal, org_id, body)
    return OrgOut.model_validate(org)


@orgs_router.post("/orgs/{org_id}/suspend")
async def suspend_org(
    org_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> OrgOut:
    org = await TenancyService(session, kv).set_org_status(principal, org_id, SUSPENDED)
    return OrgOut.model_validate(org)


@orgs_router.post("/orgs/{org_id}/activate")
async def activate_org(
    org_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> OrgOut:
    org = await TenancyService(session, kv).set_org_status(principal, org_id, ACTIVE)
    return OrgOut.model_validate(org)


# ---- malls ----


@malls_router.post("/orgs/{org_id}/malls", status_code=status.HTTP_201_CREATED)
async def create_mall(
    org_id: uuid.UUID, body: MallCreate, principal: Staff, session: SessionDep, kv: KvDep
) -> MallOut:
    mall = await TenancyService(session, kv).create_mall(principal, org_id, body)
    return MallOut.model_validate(mall)


@malls_router.get("/orgs/{org_id}/malls")
async def list_malls(
    org_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> list[MallOut]:
    malls = await TenancyService(session, kv).list_malls(principal, org_id)
    return [MallOut.model_validate(m) for m in malls]


@malls_router.get("/malls/{mall_id}")
async def get_mall(mall_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep) -> MallOut:
    return MallOut.model_validate(await TenancyService(session, kv).get_mall(principal, mall_id))


@malls_router.patch("/malls/{mall_id}")
async def update_mall(
    mall_id: uuid.UUID, body: MallUpdate, principal: Staff, session: SessionDep, kv: KvDep
) -> MallOut:
    mall = await TenancyService(session, kv).update_mall(principal, mall_id, body)
    return MallOut.model_validate(mall)


@malls_router.post("/malls/{mall_id}/suspend")
async def suspend_mall(
    mall_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> MallOut:
    mall = await TenancyService(session, kv).set_mall_status(principal, mall_id, SUSPENDED)
    return MallOut.model_validate(mall)


@malls_router.post("/malls/{mall_id}/activate")
async def activate_mall(
    mall_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> MallOut:
    mall = await TenancyService(session, kv).set_mall_status(principal, mall_id, ACTIVE)
    return MallOut.model_validate(mall)


# ---- stores ----


@stores_router.post("/malls/{mall_id}/stores", status_code=status.HTTP_201_CREATED)
async def create_store(
    mall_id: uuid.UUID, body: StoreCreate, principal: Staff, session: SessionDep, kv: KvDep
) -> StoreOut:
    store = await TenancyService(session, kv).create_store(principal, mall_id, body)
    return StoreOut.model_validate(store)


@stores_router.get("/malls/{mall_id}/stores")
async def list_stores(
    mall_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> list[StoreOut]:
    stores = await TenancyService(session, kv).list_stores(principal, mall_id)
    return [StoreOut.model_validate(s) for s in stores]


@stores_router.get("/stores/{store_id}")
async def get_store(
    store_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> StoreOut:
    store = await TenancyService(session, kv).get_store(principal, store_id)
    return StoreOut.model_validate(store)


@stores_router.patch("/stores/{store_id}")
async def update_store(
    store_id: uuid.UUID, body: StoreUpdate, principal: Staff, session: SessionDep, kv: KvDep
) -> StoreOut:
    store = await TenancyService(session, kv).update_store(principal, store_id, body)
    return StoreOut.model_validate(store)


@stores_router.post("/stores/{store_id}/suspend")
async def suspend_store(
    store_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> StoreOut:
    store = await TenancyService(session, kv).set_store_status(principal, store_id, SUSPENDED)
    return StoreOut.model_validate(store)


@stores_router.post("/stores/{store_id}/activate")
async def activate_store(
    store_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> StoreOut:
    store = await TenancyService(session, kv).set_store_status(principal, store_id, ACTIVE)
    return StoreOut.model_validate(store)


# ---- public ----


@public_router.get("/malls/{slug}")
async def get_public_mall(
    slug: str, response: Response, session: SessionDep, kv: KvDep
) -> PublicMallOut:
    response.headers["Cache-Control"] = "public, max-age=30"
    return await TenancyService(session, kv).public_mall(slug)


routers = [orgs_router, malls_router, stores_router, public_router]
