import uuid

from fastapi import APIRouter, Response

from mallt.core.db import SessionDep
from mallt.modules.iam.deps import KvDep, Staff
from mallt.modules.platform.schemas import (
    DirectoryOut,
    FeaturedSpotCreate,
    FeaturedSpotOut,
    FeatureOut,
    FeaturesOut,
    FeatureUpdate,
)
from mallt.modules.platform.service import FeatureService, PlatformService

public_router = APIRouter(prefix="/api/v1", tags=["features"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["owner"])


@public_router.get("/features")
async def get_features(response: Response, session: SessionDep) -> FeaturesOut:
    response.headers["Cache-Control"] = "public, max-age=15"
    return FeaturesOut(flags=await FeatureService(session).all())


@admin_router.get("/features")
async def list_features(principal: Staff, session: SessionDep, kv: KvDep) -> list[FeatureOut]:
    return await PlatformService(session, kv).list_features(principal)


@admin_router.put("/features/{key}")
async def set_feature(
    key: str, body: FeatureUpdate, principal: Staff, session: SessionDep, kv: KvDep
) -> FeatureOut:
    return await PlatformService(session, kv).set_feature(principal, key, body.enabled)


@admin_router.get("/directory")
async def directory(principal: Staff, session: SessionDep, kv: KvDep) -> DirectoryOut:
    return await PlatformService(session, kv).directory(principal)


@admin_router.get("/featured")
async def list_featured(
    principal: Staff, session: SessionDep, kv: KvDep, mall_id: uuid.UUID | None = None
) -> list[FeaturedSpotOut]:
    return await PlatformService(session, kv).list_spots(principal, mall_id)


@admin_router.post("/featured", status_code=201)
async def grant_featured(
    body: FeaturedSpotCreate, principal: Staff, session: SessionDep, kv: KvDep
) -> FeaturedSpotOut:
    return await PlatformService(session, kv).grant_spot(principal, body)


@admin_router.post("/featured/{spot_id}/revoke")
async def revoke_featured(
    spot_id: uuid.UUID, principal: Staff, session: SessionDep, kv: KvDep
) -> FeaturedSpotOut:
    return await PlatformService(session, kv).revoke_spot(principal, spot_id)
