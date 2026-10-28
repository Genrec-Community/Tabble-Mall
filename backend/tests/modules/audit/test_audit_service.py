from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.ids import uuid7
from mallt.core.logging import _client_ip, _request_id
from mallt.core.rbac import Scope
from mallt.modules.audit.models import AuditLog
from mallt.modules.audit.service import Actor, AuditService
from tests.factories import make_mall, make_org, make_store, store_scope


async def test_audit_record_persists_scope_ids(db_session: AsyncSession) -> None:
    org = await make_org(db_session)
    mall = await make_mall(db_session, org)
    store = await make_store(db_session, mall)
    actor_id, target_id = uuid7(), uuid7()

    await AuditService(db_session).record(
        actor=Actor(ActorType.STAFF, actor_id),
        action="staff.created",
        target_type="staff_user",
        target_id=target_id,
        scope=store_scope(store),
        before=None,
        after={"username": "cashier"},
    )

    row = (await db_session.execute(select(AuditLog))).scalar_one()
    assert (row.actor_type, row.actor_id, row.action) == (
        ActorType.STAFF,
        actor_id,
        "staff.created",
    )
    assert (row.target_type, row.target_id) == ("staff_user", target_id)
    assert (row.organization_id, row.mall_id, row.store_id) == (org.id, mall.id, store.id)
    assert row.after == {"username": "cashier"} and row.before is None


async def test_audit_picks_up_request_context_and_platform_scope(db_session: AsyncSession) -> None:
    rid_token, ip_token = _request_id.set("req-123"), _client_ip.set("203.0.113.9")
    try:
        await AuditService(db_session).record(
            actor=Actor(ActorType.SYSTEM, None),
            action="org.created",
            target_type="organization",
            target_id=uuid7(),
            scope=Scope.platform(),
        )
    finally:
        _request_id.reset(rid_token)
        _client_ip.reset(ip_token)

    row = (await db_session.execute(select(AuditLog))).scalar_one()
    assert (row.request_id, row.ip) == ("req-123", "203.0.113.9")
    assert (row.organization_id, row.mall_id, row.store_id) == (None, None, None)
