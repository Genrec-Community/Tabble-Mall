"""Runs the money outbox: right after a request that queued work commits, and from the sweeper.
Each task runs and commits in its own transaction, so one stuck task never holds up the rest."""

import logging
from typing import Any

from mallt.modules.payments.service import Kick, PaymentsService

log = logging.getLogger(__name__)


async def run_money_tasks(app: Any, limit: int = 25) -> int:
    done = 0
    while done < limit:
        async with app.state.session_factory() as session:
            service = PaymentsService(session, app.state.kv, app.state.payments)
            worked = await service.process_next()
            await session.commit()
        if not worked:
            break
        done += 1
    return done


def money_kick(app: Any) -> Kick:
    async def kick() -> None:
        await run_money_tasks(app)

    return kick
