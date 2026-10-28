"""The socket a print agent holds open. The agent dials out; the server polls its queue.

One coroutine does all reading and writing: drain what is queued, wait for a frame until the poll
interval expires, drain again. The store comes from the authenticated agent row, never from
anything the agent says. Each drain and each ack commits on its own so a dropped socket cannot
roll back an ack for paper that already came out.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, NamedTuple, Protocol

from fastapi import FastAPI

from mallt.modules.printing import agents
from mallt.modules.printing.queue import PrintQueue
from mallt.modules.printing.repository import PrintingRepository
from mallt.modules.printing.service import PrintingService, scan_key

log = logging.getLogger(__name__)
POLL_SECONDS = 3.0
#: A revoked agent is cut off within RECHECK_EVERY_POLLS * POLL_SECONDS (30 s), not at next connect.
RECHECK_EVERY_POLLS = 10
AUTH_TIMEOUT_S = 10.0
MAX_AUTH_FRAME = 2048
MAX_FRAME = 65536
CLOSE_POLICY = 1008


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def receive_text(self) -> str: ...
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


class _Auth(NamedTuple):
    token: str
    probe: bool
    version: str | None


async def _auth_frame(ws: WebSocketLike) -> _Auth | None:
    try:
        async with asyncio.timeout(AUTH_TIMEOUT_S):
            raw = await ws.receive_text()
        if len(raw) > MAX_AUTH_FRAME:
            return None
        message = json.loads(raw)
    except (TimeoutError, json.JSONDecodeError):
        return None
    token = message.get("token") if isinstance(message, dict) else None
    if not isinstance(token, str) or not token:
        return None
    version = message.get("version")
    return _Auth(token, message.get("probe") is True, version if isinstance(version, str) else None)


def _frame(kind: str, **fields: Any) -> str:
    return json.dumps({"type": kind, **fields})


async def serve_agent(ws: WebSocketLike, app: FastAPI) -> None:
    await ws.accept()
    auth = await _auth_frame(ws)
    if auth is None:
        await ws.close(code=CLOSE_POLICY)
        return
    factory = app.state.session_factory
    kv = app.state.kv
    async with factory() as session:
        agent = await agents.authenticate(session, auth.token)
        if agent is None:  # one answer for malformed, unknown, wrong secret and revoked alike
            await ws.close(code=CLOSE_POLICY)
            return
        store_id, agent_id = agent.store_id, agent.id
        if not auth.probe:
            await agents.mark_seen(session, agent, auth.version)
            await session.commit()
    await ws.send_text(_frame("ready", agent_id=str(agent_id)))
    if auth.probe:
        await ws.close(code=1000)
        return

    in_flight: set[uuid.UUID] = set()
    polls = 0
    try:
        while True:
            polls += 1
            if polls % RECHECK_EVERY_POLLS == 0:
                async with factory() as session:
                    current = await PrintingRepository(session).agent(agent_id)
                if current is None or not current.is_active:  # revoked while connected
                    await ws.close(code=CLOSE_POLICY)
                    return
            async with factory() as session:
                frames = await PrintQueue(session).claim(store_id)
                await session.commit()
            for frame in frames:
                in_flight.add(uuid.UUID(frame["job_id"]))
                await ws.send_text(_frame("job", job=frame))
            if await kv.get(scan_key(agent_id)):
                await kv.delete(scan_key(agent_id))
                await ws.send_text(_frame("scan_lan"))
            try:
                async with asyncio.timeout(POLL_SECONDS):
                    raw = await ws.receive_text()
            except TimeoutError:
                await ws.send_text(_frame("heartbeat"))  # failing send = agent gone
                continue
            await _handle(app, agent_id, store_id, raw, in_flight)
    except Exception:  # noqa: BLE001 - an agent vanishing is ordinary
        log.debug("print agent socket for %s ended", agent_id, exc_info=True)
    finally:
        if in_flight:
            async with factory() as session:
                n = await PrintQueue(session).requeue_unacked(store_id, list(in_flight))
                await session.commit()
            log.info(
                "print agent %s left holding %d job(s); %d requeued", agent_id, len(in_flight), n
            )


async def _handle(
    app: FastAPI, agent_id: uuid.UUID, store_id: uuid.UUID, raw: str, in_flight: set[uuid.UUID]
) -> None:
    if len(raw) > MAX_FRAME:
        return
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(message, dict):
        return
    kind = message.get("type")
    factory = app.state.session_factory
    if kind in ("printed", "failed"):
        try:
            job_id = uuid.UUID(str(message.get("job_id")))
        except ValueError:
            return
        if job_id not in in_flight:  # not handed to this socket (e.g. a sibling agent's job)
            return
        async with factory() as session:
            queue = PrintQueue(session)
            if kind == "printed":
                await queue.mark_printed(store_id, job_id)
            else:
                error = message.get("error")
                await queue.mark_failed(store_id, job_id, error if isinstance(error, str) else "?")
            await session.commit()
        in_flight.discard(job_id)
    elif kind == "printers":
        items = message.get("items")
        if not isinstance(items, list):
            return
        async with factory() as session:
            agent = await PrintingRepository(session).agent(agent_id)
            if agent is not None and agent.is_active:
                await PrintingService(session, app.state.kv).record_detected(
                    agent,
                    [i for i in items if isinstance(i, dict)],
                    scope="lan" if message.get("scope") == "lan" else "local",
                )
                await session.commit()
