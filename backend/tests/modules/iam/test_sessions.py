from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.db import run_after_commit
from mallt.core.enums import IdentityKind
from mallt.modules.iam.sessions import SessionService
from tests.factories import MemoryKV, make_staff


async def test_revoking_a_session_clears_its_cache_again_after_commit(
    db_session: AsyncSession,
) -> None:
    kv = MemoryKV()
    staff = await make_staff(db_session, "asha")
    sessions = SessionService(db_session, Settings(env="test", _env_file=None), kv)  # type: ignore[call-arg]
    _, row = await sessions.issue(IdentityKind.STAFF, staff.id)
    await db_session.flush()
    key = f"sess:{row.family_id}"

    await sessions.revoke_family(row.family_id)
    await kv.set(key, "1", 30)  # a racing request re-cached "still active" before the commit

    await run_after_commit(db_session)
    assert await kv.get(key) is None
