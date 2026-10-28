import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus, ActorType
from mallt.core.errors import Conflict, NotFound
from mallt.core.kv import KV
from mallt.core.pagination import Page
from mallt.core.rbac import P, Scope
from mallt.core.security import new_temp_password
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.iam.users import IamUsers
from mallt.modules.tenancy.models import Mall, Organization, Store
from mallt.modules.tenancy.repository import TenancyRepository
from mallt.modules.tenancy.schemas import (
    MallCreate,
    MallUpdate,
    OrgCreate,
    OrgCreatedOut,
    OrgOut,
    OrgUpdate,
    PublicMallOut,
    PublicStoreOut,
    StoreCreate,
    StoreUpdate,
)

# Commission is MallT's own revenue, so only the platform may change it (not the tenant).
COMMISSION_PERMISSION = P.PLATFORM_ORG_MANAGE


def _snapshot(obj: Any, fields: Any) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


class TenancyService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.repo = TenancyRepository(session)
        self.authz = AuthzService(session, kv)
        self.audit = AuditService(session)
        self.users = IamUsers(session)

    # ---- scope lookups (also used by the staff module) ----

    async def scope_for_org(self, org_id: uuid.UUID) -> Scope:
        return Scope.org((await self._org(org_id)).id)

    async def scope_for_mall(self, mall_id: uuid.UUID) -> Scope:
        mall = await self._mall(mall_id)
        return Scope.mall(mall.organization_id, mall.id)

    async def scope_for_store(self, store_id: uuid.UUID) -> Scope:
        store = await self._store(store_id)
        return Scope.store(store.organization_id, store.mall_id, store.id)

    # ---- loading with visibility (unseen tenants are 404) ----

    async def _org(self, org_id: uuid.UUID) -> Organization:
        org = await self.repo.get_org(org_id)
        if org is None:
            raise NotFound("not_found", "Not found.")
        return org

    async def _mall(self, mall_id: uuid.UUID) -> Mall:
        mall = await self.repo.get_mall(mall_id)
        if mall is None:
            raise NotFound("not_found", "Not found.")
        return mall

    async def _store(self, store_id: uuid.UUID) -> Store:
        store = await self.repo.get_store(store_id)
        if store is None:
            raise NotFound("not_found", "Not found.")
        return store

    async def _visible_org(self, principal: Principal, org_id: uuid.UUID) -> Organization:
        org = await self._org(org_id)
        self.authz.require_visible(principal, Scope.org(org.id))
        return org

    async def _visible_mall(self, principal: Principal, mall_id: uuid.UUID) -> Mall:
        mall = await self._mall(mall_id)
        self.authz.require_visible(principal, Scope.mall(mall.organization_id, mall.id))
        return mall

    async def _visible_store(self, principal: Principal, store_id: uuid.UUID) -> Store:
        store = await self._store(store_id)
        self.authz.require_visible(
            principal, Scope.store(store.organization_id, store.mall_id, store.id)
        )
        return store

    def _ensure_operational(
        self, principal: Principal, org: Organization, mall: Mall | None = None
    ) -> None:
        """Tenants can't change things under a suspended org or mall (the platform still can)."""
        if self.authz.visible_org_ids(principal) is None:
            return
        if org.status != ActiveStatus.ACTIVE or (mall and mall.status != ActiveStatus.ACTIVE):
            raise Conflict("suspended", "This organization or mall is suspended.")

    async def _record(
        self,
        principal: Principal,
        action: str,
        target_type: str,
        target_id: uuid.UUID,
        scope: Scope,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
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

    # ---- organizations ----

    async def create_org(self, principal: Principal, data: OrgCreate) -> OrgCreatedOut:
        self.authz.require(principal, P.PLATFORM_ORG_MANAGE, Scope.platform())
        org = Organization(name=data.name, slug=data.slug)
        await self.repo.add_unique(org)
        temp_password = new_temp_password()
        owner = await self.users.create_staff_user(
            username=data.owner.username,
            display_name=data.owner.display_name,
            email=data.owner.email,
            password=temp_password,
            must_change_password=True,
        )
        await self.users.assign_role(
            owner.id, "org_owner", Scope.org(org.id), granted_by=principal.staff_id
        )
        await self._record(
            principal,
            "org.created",
            "organization",
            org.id,
            Scope.org(org.id),
            after={"name": org.name, "slug": org.slug, "owner": owner.username},
        )
        return OrgCreatedOut(
            org=OrgOut.model_validate(org),
            owner_username=owner.username,
            temp_password=temp_password,
        )

    async def list_orgs(
        self, principal: Principal, cursor: uuid.UUID | None, limit: int
    ) -> Page[OrgOut]:
        rows = await self.repo.list_orgs(self.authz.visible_org_ids(principal), cursor, limit + 1)
        page = rows[:limit]
        return Page[OrgOut](
            items=[OrgOut.model_validate(o) for o in page],
            next_cursor=page[-1].id if len(rows) > limit else None,
        )

    async def get_org(self, principal: Principal, org_id: uuid.UUID) -> Organization:
        return await self._visible_org(principal, org_id)

    async def update_org(
        self, principal: Principal, org_id: uuid.UUID, data: OrgUpdate
    ) -> Organization:
        org = await self._visible_org(principal, org_id)
        scope = Scope.org(org.id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        if not changes:
            return org
        if "commission_bps" in changes:
            self.authz.require(principal, COMMISSION_PERMISSION, Scope.platform())
        if changes.keys() & {"name", "accept_timeout_s"}:
            self.authz.require(principal, P.ORG_SETTINGS_UPDATE, scope)
        self._ensure_operational(principal, org)
        before = _snapshot(org, changes)
        for field, value in changes.items():
            setattr(org, field, value)
        await self._record(principal, "org.updated", "organization", org.id, scope, before, changes)
        return org

    async def set_org_status(
        self, principal: Principal, org_id: uuid.UUID, status: ActiveStatus
    ) -> Organization:
        org = await self._visible_org(principal, org_id)
        self.authz.require(principal, P.PLATFORM_ORG_MANAGE, Scope.platform())
        if org.status != status:
            before = {"status": org.status.value}
            org.status = status
            verb = "suspended" if status == ActiveStatus.SUSPENDED else "activated"
            await self._record(
                principal,
                f"org.{verb}",
                "organization",
                org.id,
                Scope.org(org.id),
                before,
                {"status": status.value},
            )
        return org

    # ---- malls ----

    async def create_mall(self, principal: Principal, org_id: uuid.UUID, data: MallCreate) -> Mall:
        org = await self._visible_org(principal, org_id)
        self.authz.require(principal, P.ORG_MALL_MANAGE, Scope.org(org.id))
        self._ensure_operational(principal, org)
        mall = Mall(
            organization_id=org.id,
            name=data.name,
            slug=data.slug,
            city=data.city,
            address=data.address,
        )
        await self.repo.add_unique(mall)
        await self._record(
            principal,
            "mall.created",
            "mall",
            mall.id,
            Scope.mall(org.id, mall.id),
            after={"name": mall.name, "slug": mall.slug},
        )
        return mall

    async def list_malls(self, principal: Principal, org_id: uuid.UUID) -> list[Mall]:
        org = await self._visible_org(principal, org_id)
        return [
            m
            for m in await self.repo.list_malls(org.id)
            if self.authz.can_see(principal, Scope.mall(org.id, m.id))
        ]

    async def get_mall(self, principal: Principal, mall_id: uuid.UUID) -> Mall:
        return await self._visible_mall(principal, mall_id)

    async def update_mall(self, principal: Principal, mall_id: uuid.UUID, data: MallUpdate) -> Mall:
        mall = await self._visible_mall(principal, mall_id)
        scope = Scope.mall(mall.organization_id, mall.id)
        self.authz.require(principal, P.ORG_MALL_MANAGE, scope)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        if not changes:
            return mall
        org = await self._org(mall.organization_id)
        self._ensure_operational(principal, org, mall)
        before = _snapshot(mall, changes)
        for field, value in changes.items():
            setattr(mall, field, value)
        await self._record(principal, "mall.updated", "mall", mall.id, scope, before, changes)
        return mall

    async def set_mall_status(
        self, principal: Principal, mall_id: uuid.UUID, status: ActiveStatus
    ) -> Mall:
        mall = await self._visible_mall(principal, mall_id)
        scope = Scope.mall(mall.organization_id, mall.id)
        self.authz.require(principal, P.ORG_MALL_MANAGE, scope)
        self._ensure_operational(principal, await self._org(mall.organization_id))
        if mall.status != status:
            before = {"status": mall.status.value}
            mall.status = status
            verb = "suspended" if status == ActiveStatus.SUSPENDED else "activated"
            await self._record(
                principal, f"mall.{verb}", "mall", mall.id, scope, before, {"status": status.value}
            )
        return mall

    # ---- stores ----

    async def create_store(
        self, principal: Principal, mall_id: uuid.UUID, data: StoreCreate
    ) -> Store:
        mall = await self._visible_mall(principal, mall_id)
        self.authz.require(principal, P.ORG_STORE_MANAGE, Scope.mall(mall.organization_id, mall.id))
        self._ensure_operational(principal, await self._org(mall.organization_id), mall)
        store = Store(
            organization_id=mall.organization_id,
            mall_id=mall.id,
            name=data.name,
            slug=data.slug,
            description=data.description,
        )
        await self.repo.add_unique(store)
        await self._record(
            principal,
            "store.created",
            "store",
            store.id,
            Scope.store(store.organization_id, store.mall_id, store.id),
            after={"name": store.name, "slug": store.slug},
        )
        return store

    async def list_stores(self, principal: Principal, mall_id: uuid.UUID) -> list[Store]:
        mall = await self._visible_mall(principal, mall_id)
        return [
            s
            for s in await self.repo.list_stores(mall.id)
            if self.authz.can_see(principal, Scope.store(s.organization_id, s.mall_id, s.id))
        ]

    async def get_store(self, principal: Principal, store_id: uuid.UUID) -> Store:
        return await self._visible_store(principal, store_id)

    async def update_store(
        self, principal: Principal, store_id: uuid.UUID, data: StoreUpdate
    ) -> Store:
        store = await self._visible_store(principal, store_id)
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] is None:
            del changes["name"]
        if not changes:
            return store
        if "name" in changes:
            self.authz.require(principal, P.ORG_STORE_MANAGE, scope)
        if "description" in changes:
            self.authz.require(principal, P.STORE_PROFILE_UPDATE, scope)
        if "commission_bps" in changes:
            self.authz.require(principal, COMMISSION_PERMISSION, Scope.platform())
        self._ensure_operational(
            principal,
            await self._org(store.organization_id),
            await self._mall(store.mall_id),
        )
        before = _snapshot(store, changes)
        for field, value in changes.items():
            setattr(store, field, value)
        await self._record(principal, "store.updated", "store", store.id, scope, before, changes)
        return store

    async def set_store_status(
        self, principal: Principal, store_id: uuid.UUID, status: ActiveStatus
    ) -> Store:
        store = await self._visible_store(principal, store_id)
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, P.ORG_STORE_MANAGE, scope)
        self._ensure_operational(
            principal,
            await self._org(store.organization_id),
            await self._mall(store.mall_id),
        )
        if store.status != status:
            before = {"status": store.status.value}
            store.status = status
            verb = "suspended" if status == ActiveStatus.SUSPENDED else "activated"
            await self._record(
                principal,
                f"store.{verb}",
                "store",
                store.id,
                scope,
                before,
                {"status": status.value},
            )
        return store

    # ---- public ----

    async def public_mall(self, slug: str) -> PublicMallOut:
        found = await self.repo.public_mall(slug)
        if found is None:
            raise NotFound("not_found", "Not found.")
        mall, stores = found
        return PublicMallOut(
            name=mall.name,
            slug=mall.slug,
            city=mall.city,
            stores=[PublicStoreOut.model_validate(s) for s in stores],
        )
