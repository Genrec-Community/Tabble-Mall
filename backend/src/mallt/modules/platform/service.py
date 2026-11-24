"""Platform-owner controls: feature switches and featured spots."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.errors import BadRequest, NotFound
from mallt.core.features import FEATURES, defaults
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.platform.models import FeaturedSpot, PlatformFeature
from mallt.modules.platform.repository import PlatformRepository
from mallt.modules.platform.schemas import (
    DirectoryMallOut,
    DirectoryOrgOut,
    DirectoryOut,
    DirectoryStoreOut,
    FeaturedSpotCreate,
    FeaturedSpotOut,
    FeatureOut,
)
from mallt.modules.tenancy.service import TenancyService


class FeatureService:
    """Read the feature switches. No authorization: they are public."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = PlatformRepository(session)

    async def all(self) -> dict[str, bool]:
        flags = defaults()
        for row in await self.repo.feature_rows():
            if row.key in flags:
                flags[row.key] = row.enabled
        return flags

    async def is_enabled(self, key: str) -> bool:
        if key not in FEATURES:
            raise KeyError(f"unknown feature {key!r}; add it to core/features.py")
        row = await self.repo.get_feature(key)
        return row.enabled if row is not None else FEATURES[key].default

    async def require(self, key: str) -> None:
        """Refuse a request for a feature the owner has switched off."""
        if not await self.is_enabled(key):
            raise NotFound("feature_off", "This feature is switched off.")

    async def featured_store_ids(self, mall_id: uuid.UUID) -> list[uuid.UUID]:
        """The mall's featured stores right now; none while featured spots are switched off."""
        if not await self.is_enabled("featured_spots"):
            return []
        return await self.repo.live_store_ids(mall_id, datetime.now(UTC))


class PlatformService:
    """The platform owner's dashboard. Everything here needs ``platform.org.manage``."""

    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.repo = PlatformRepository(session)
        self.features = FeatureService(session)
        self.authz = AuthzService(session, kv)
        self.audit = AuditService(session)
        self.tenancy = TenancyService(session, kv)

    def _require(self, principal: Principal) -> None:
        self.authz.require(principal, P.PLATFORM_ORG_MANAGE, Scope.platform())

    async def _record(
        self,
        principal: Principal,
        action: str,
        target_type: str,
        target_id: uuid.UUID | None,
        scope: Scope | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        await self.audit.record(
            actor=Actor(ActorType.STAFF, principal.staff_id),
            action=action,
            target_type=target_type,
            target_id=target_id,
            scope=scope,
            before=before,
            after=after,
        )

    # ---- feature switches ----

    async def list_features(self, principal: Principal) -> list[FeatureOut]:
        self._require(principal)
        flags = await self.features.all()
        return [
            FeatureOut(
                key=f.key,
                label=f.label,
                description=f.description,
                group=f.group,
                default=f.default,
                enabled=flags[f.key],
            )
            for f in FEATURES.values()
        ]

    async def set_feature(self, principal: Principal, key: str, enabled: bool) -> FeatureOut:
        self._require(principal)
        if key not in FEATURES:
            raise NotFound("not_found", "Not found.")
        before = await self.features.is_enabled(key)
        row = await self.repo.get_feature(key)
        if row is None:
            row = PlatformFeature(key=key, enabled=enabled, updated_by=principal.staff_id)
            self.repo.add(row)
        else:
            row.enabled, row.updated_by = enabled, principal.staff_id
        await self.repo.flush()
        if before != enabled:
            await self._record(
                principal,
                "feature.updated",
                "feature",
                None,
                None,
                {"key": key, "enabled": before},
                {"key": key, "enabled": enabled},
            )
        f = FEATURES[key]
        return FeatureOut(
            key=key,
            label=f.label,
            description=f.description,
            group=f.group,
            default=f.default,
            enabled=enabled,
        )

    # ---- featured spots ----

    async def _spots_out(self, spots: list[FeaturedSpot]) -> list[FeaturedSpotOut]:
        stores = await self.tenancy.stores_by_ids([s.store_id for s in spots])
        malls = await self.tenancy.malls_by_ids([s.mall_id for s in spots])
        now = datetime.now(UTC)
        return [
            FeaturedSpotOut(
                id=s.id,
                organization_id=s.organization_id,
                mall_id=s.mall_id,
                store_id=s.store_id,
                store_name=stores[s.store_id].name,
                mall_name=malls[s.mall_id].name,
                starts_at=s.starts_at,
                ends_at=s.ends_at,
                amount_paise=s.amount_paise,
                note=s.note,
                revoked_at=s.revoked_at,
                live=s.revoked_at is None
                and s.starts_at <= now
                and (s.ends_at is None or s.ends_at > now),
            )
            for s in spots
        ]

    async def list_spots(
        self, principal: Principal, mall_id: uuid.UUID | None
    ) -> list[FeaturedSpotOut]:
        self._require(principal)
        return await self._spots_out(await self.repo.list_spots(mall_id))

    async def grant_spot(self, principal: Principal, data: FeaturedSpotCreate) -> FeaturedSpotOut:
        self._require(principal)
        store = (await self.tenancy.stores_by_ids([data.store_id])).get(data.store_id)
        if store is None:
            raise NotFound("not_found", "Not found.")
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        starts = data.starts_at or datetime.now(UTC)
        if data.ends_at is not None and data.ends_at <= starts:
            raise BadRequest("bad_dates", "The end must be after the start.")
        spot = FeaturedSpot(
            organization_id=store.organization_id,
            mall_id=store.mall_id,
            store_id=store.id,
            starts_at=starts,
            ends_at=data.ends_at,
            amount_paise=data.amount_paise,
            note=data.note,
            created_by=principal.staff_id,
        )
        self.repo.add(spot)
        await self.repo.flush()
        await self._record(
            principal,
            "featured.granted",
            "featured_spot",
            spot.id,
            scope,
            None,
            {
                "store_id": str(data.store_id),
                "starts_at": starts.isoformat(),
                "ends_at": data.ends_at.isoformat() if data.ends_at else None,
                "amount_paise": data.amount_paise,
            },
        )
        return (await self._spots_out([spot]))[0]

    async def revoke_spot(self, principal: Principal, spot_id: uuid.UUID) -> FeaturedSpotOut:
        self._require(principal)
        spot = await self.repo.get_spot(spot_id)
        if spot is None:
            raise NotFound("not_found", "Not found.")
        if spot.revoked_at is None:
            spot.revoked_at = datetime.now(UTC)
            await self.repo.flush()
            await self._record(
                principal,
                "featured.revoked",
                "featured_spot",
                spot.id,
                Scope.store(spot.organization_id, spot.mall_id, spot.store_id),
                None,
                None,
            )
        return (await self._spots_out([spot]))[0]

    # ---- everything at a glance ----

    async def directory(self, principal: Principal) -> DirectoryOut:
        orgs, malls, stores = await self.tenancy.everything(principal)
        featured = set(await self.repo.live_store_ids(None, datetime.now(UTC)))
        by_mall: dict[uuid.UUID, list[DirectoryStoreOut]] = {}
        for s in stores:
            by_mall.setdefault(s.mall_id, []).append(
                DirectoryStoreOut(
                    id=s.id, name=s.name, slug=s.slug, status=s.status, featured=s.id in featured
                )
            )
        by_org: dict[uuid.UUID, list[DirectoryMallOut]] = {}
        for m in malls:
            by_org.setdefault(m.organization_id, []).append(
                DirectoryMallOut(
                    id=m.id,
                    name=m.name,
                    slug=m.slug,
                    status=m.status,
                    stores=by_mall.get(m.id, []),
                )
            )
        return DirectoryOut(
            orgs=[
                DirectoryOrgOut(
                    id=o.id,
                    name=o.name,
                    slug=o.slug,
                    status=o.status,
                    malls=by_org.get(o.id, []),
                )
                for o in orgs
            ]
        )
