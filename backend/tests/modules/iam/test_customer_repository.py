from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActiveStatus
from mallt.modules.iam.models import Customer
from mallt.modules.iam.repository import CustomerRepository


async def test_create_assigns_an_id_and_reports_a_unique_clash_as_none(
    db_session: AsyncSession,
) -> None:
    repo = CustomerRepository(db_session)
    first = await repo.create(Customer(phone="9361899061", status=ActiveStatus.ACTIVE))
    assert first is not None and first.id is not None

    # Two first-time logins racing for the same number: the loser gets None, not a crash.
    assert await repo.create(Customer(phone="9361899061", status=ActiveStatus.ACTIVE)) is None
    assert (await repo.by_phone("9361899061")) is first

    assert await repo.create(Customer(google_sub="g-1", status=ActiveStatus.ACTIVE)) is not None
    assert await repo.create(Customer(google_sub="g-1", status=ActiveStatus.ACTIVE)) is None
