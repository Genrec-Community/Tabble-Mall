import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus
from mallt.core.errors import Conflict
from mallt.modules.tenancy.models import Mall, Organization, Store


class TenancyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_unique(self, obj: Organization | Mall | Store) -> None:
        """Insert, turning a unique-slug clash into a 409 without poisoning the transaction."""
        try:
            async with self.session.begin_nested():
                self.session.add(obj)
                await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("slug_taken", "That slug is already in use.") from exc

    async def get_org(self, org_id: uuid.UUID) -> Organization | None:
        return await self.session.get(Organization, org_id)

    async def list_orgs(
        self, visible_ids: set[uuid.UUID] | None, after: uuid.UUID | None, limit: int
    ) -> list[Organization]:
        stmt = select(Organization).order_by(Organization.id).limit(limit)
        if visible_ids is not None:
            stmt = stmt.where(Organization.id.in_(visible_ids))
        if after is not None:
            stmt = stmt.where(Organization.id > after)
        return list((await self.session.execute(stmt)).scalars())

    async def get_mall(self, mall_id: uuid.UUID) -> Mall | None:
        return await self.session.get(Mall, mall_id)

    async def list_malls(self, org_id: uuid.UUID) -> list[Mall]:
        stmt = select(Mall).where(Mall.organization_id == org_id).order_by(Mall.id)
        return list((await self.session.execute(stmt)).scalars())

    async def get_store(self, store_id: uuid.UUID) -> Store | None:
        return await self.session.get(Store, store_id)

    async def list_stores(self, mall_id: uuid.UUID) -> list[Store]:
        stmt = select(Store).where(Store.mall_id == mall_id).order_by(Store.id)
        return list((await self.session.execute(stmt)).scalars())

    async def public_mall(self, slug: str) -> tuple[Mall, list[Store]] | None:
        """An active mall of an active organization, with its active stores."""
        stmt = (
            select(Mall)
            .join(Organization, Organization.id == Mall.organization_id)
            .where(
                Mall.slug == slug,
                Mall.status == ActiveStatus.ACTIVE,
                Organization.status == ActiveStatus.ACTIVE,
            )
        )
        mall = (await self.session.execute(stmt)).scalar_one_or_none()
        if mall is None:
            return None
        stores = (
            select(Store)
            .where(Store.mall_id == mall.id, Store.status == ActiveStatus.ACTIVE)
            .order_by(Store.name, Store.id)
        )
        return mall, list((await self.session.execute(stores)).scalars())
