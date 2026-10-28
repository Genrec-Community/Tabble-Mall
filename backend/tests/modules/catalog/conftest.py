from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.rbac import Scope
from mallt.modules.tenancy.models import Mall, Organization, Store
from tests.factories import make_mall, make_org, make_staff, make_store, store_scope
from tests.helpers import staff_headers


@dataclass
class World:
    org: Organization
    mall: Mall
    store: Store
    other_store: Store
    owner: dict[str, str]  # store owner of `store`
    staff: dict[str, str]  # store staff of `store`
    org_owner: dict[str, str]
    outsider: dict[str, str]  # store owner in another organization
    other_store_owner: dict[str, str]  # same mall, different store


@pytest.fixture
async def world(client: httpx.AsyncClient, db_session: AsyncSession) -> World:
    org = await make_org(db_session, "phoenix")
    mall = await make_mall(db_session, org, "phoenix-pune")
    store = await make_store(db_session, mall, "burger-hub")
    other_store = await make_store(db_session, mall, "chai-point")
    org2 = await make_org(db_session, "elsewhere")
    mall2 = await make_mall(db_session, org2, "elsewhere-mall")
    store2 = await make_store(db_session, mall2, "rival")
    await make_staff(db_session, "owner1", [("store_owner", store_scope(store))])
    await make_staff(db_session, "staff1", [("store_staff", store_scope(store))])
    await make_staff(db_session, "orgowner", [("org_owner", Scope.org(org.id))])
    await make_staff(db_session, "rival1", [("store_owner", store_scope(store2))])
    await make_staff(db_session, "chai1", [("store_owner", store_scope(other_store))])
    return World(
        org=org,
        mall=mall,
        store=store,
        other_store=other_store,
        owner=await staff_headers(client, "owner1"),
        staff=await staff_headers(client, "staff1"),
        org_owner=await staff_headers(client, "orgowner"),
        outsider=await staff_headers(client, "rival1"),
        other_store_owner=await staff_headers(client, "chai1"),
    )


def product_body(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Cheese Burger",
        "description": "Juicy",
        "diet": "veg",
        "prep_minutes": 12,
        "variants": [
            {"name": "Regular", "price_paise": 12000},
            {"name": "Large", "price_paise": 18000},
        ],
        "option_groups": [
            {
                "name": "Extras",
                "min_select": 0,
                "max_select": 2,
                "options": [
                    {"name": "Extra cheese", "price_delta_paise": 2000},
                    {"name": "Jalapeno", "price_delta_paise": 1500},
                ],
            }
        ],
    }
    body.update(over)
    return body
