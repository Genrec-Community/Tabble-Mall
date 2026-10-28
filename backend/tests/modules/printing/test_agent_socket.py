import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.modules.printing import ws as agent_ws
from mallt.modules.printing.models import PrintAgent, Printer, PrintJob
from mallt.modules.printing.queue import PrintQueue
from mallt.modules.printing.repository import MAX_ATTEMPTS
from tests.modules.catalog.conftest import World
from tests.modules.printing.conftest import add_printer, base


class FakeAgentSocket:
    """The agent's side of the connection: queue frames in, read the server's frames out."""

    def __init__(self, first: dict | str | None) -> None:
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        if first is not None:
            self.send(first)
        self.sent: asyncio.Queue[dict] = asyncio.Queue()
        self.closed: int | None = None

    def send(self, frame: dict | str) -> None:
        self.inbox.put_nowait(frame if isinstance(frame, str) else json.dumps(frame))

    async def accept(self) -> None: ...

    async def receive_text(self) -> str:
        item = await self.inbox.get()
        if item == "\0disconnect":
            raise ConnectionError("agent went away")
        return item

    def disconnect(self) -> None:
        self.inbox.put_nowait("\0disconnect")

    async def send_text(self, data: str) -> None:
        await self.sent.put(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        self.closed = code

    async def next(self, kind: str | None = None) -> dict:
        async with asyncio.timeout(5):
            while True:
                frame = await self.sent.get()
                if kind is None or frame["type"] == kind:
                    return frame


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_ws, "POLL_SECONDS", 0.05)


async def pair(
    client: httpx.AsyncClient, w: World, name: str = "PC", store: str = "burger"
) -> dict:
    url = base(w) if store == "burger" else f"/api/v1/stores/{w.other_store.id}"
    headers = w.owner if store == "burger" else w.other_store_owner
    r = await client.post(f"{url}/print-agents", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def run(app: FastAPI, first: dict | str | None) -> tuple[FakeAgentSocket, asyncio.Task]:
    ws = FakeAgentSocket(first)
    return ws, asyncio.ensure_future(agent_ws.serve_agent(ws, app))


async def stop(ws: FakeAgentSocket, task: asyncio.Task) -> None:
    """The agent drops the connection (no cancellation: that would abort a query mid-flight)."""
    ws.disconnect()
    async with asyncio.timeout(5):
        await task


async def test_bad_credentials_all_get_the_same_refusal(
    client: httpx.AsyncClient, app: FastAPI, world: World
) -> None:
    created = await pair(client, world)
    aid = created["agent"]["id"]
    await client.post(f"{base(world)}/print-agents/{aid}/revoke", headers=world.owner)
    cases = [
        {"token": created["token"]},  # revoked
        {"token": f"{aid}.wrong-secret"},
        {"token": f"{uuid.uuid4()}.{created['token'].split('.')[1]}"},
        {"token": "no-dot"},
        {"nope": 1},
        "not json",
        {"token": ""},
    ]
    for first in cases:
        ws = FakeAgentSocket(first)
        await agent_ws.serve_agent(ws, app)
        assert ws.closed == 1008 and ws.sent.empty(), first


async def test_probe_confirms_the_credential_and_claims_nothing(
    client: httpx.AsyncClient, app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    printer = await add_printer(client, world)
    await client.post(f"{base(world)}/printers/{printer['id']}/test", headers=world.owner)
    created = await pair(client, world)
    ws = FakeAgentSocket({"token": created["token"], "probe": True})
    await agent_ws.serve_agent(ws, app)
    assert (await ws.next())["type"] == "ready" and ws.closed == 1000
    assert ws.sent.empty()  # no job frame
    (job,) = (await db_session.execute(select(PrintJob))).scalars().all()
    assert job.status.value == "queued" and job.attempts == 0
    agent = await db_session.get(PrintAgent, uuid.UUID(created["agent"]["id"]))
    assert agent is not None and agent.last_seen_at is None


async def test_job_is_delivered_with_the_printer_details_and_acked(
    client: httpx.AsyncClient, app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    printer = await add_printer(
        client,
        world,
        "Counter",
        "counter",
        paper_width=48,
        connection="system",
        target="POS80",
        layout={"cut": "full"},
    )
    job_id = (
        await client.post(f"{base(world)}/printers/{printer['id']}/test", headers=world.owner)
    ).json()["id"]
    created = await pair(client, world)

    ws, task = await run(app, {"token": created["token"], "version": "1.0.0"})
    assert (await ws.next("ready"))["agent_id"] == created["agent"]["id"]
    frame = (await ws.next("job"))["job"]
    assert frame["job_id"] == job_id and frame["kind"] == "test"
    assert frame["connection"] == "system" and frame["target"] == "POS80"
    assert frame["paper_width"] == 48 and frame["layout"] == {"cut": "full"}
    ws.send({"type": "printed", "job_id": job_id})
    await asyncio.sleep(0.3)
    await stop(ws, task)

    job = await db_session.get(PrintJob, uuid.UUID(job_id))
    await db_session.refresh(job)
    assert job is not None and job.status.value == "printed" and job.acked_at is not None
    row = await db_session.get(Printer, uuid.UUID(printer["id"]))
    await db_session.refresh(row)
    assert row is not None and row.last_printed_at is not None
    agent = await db_session.get(PrintAgent, uuid.UUID(created["agent"]["id"]))
    await db_session.refresh(agent)
    assert agent is not None and agent.version == "1.0.0" and agent.last_seen_at is not None


async def test_a_failure_is_recorded_and_unacked_jobs_return_when_the_agent_leaves(
    client: httpx.AsyncClient, app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    printer = await add_printer(client, world)
    ids = [
        (
            await client.post(f"{base(world)}/printers/{printer['id']}/test", headers=world.owner)
        ).json()["id"]
        for _ in range(2)
    ]
    created = await pair(client, world)
    ws, task = await run(app, {"token": created["token"]})
    first = (await ws.next("job"))["job"]["job_id"]
    second = (await ws.next("job"))["job"]["job_id"]
    assert {first, second} == set(ids)
    ws.send({"type": "failed", "job_id": first, "error": "out of paper"})
    await asyncio.sleep(0.3)
    await stop(ws, task)  # the agent vanishes while still holding `second`
    await asyncio.sleep(0.1)

    rows = {str(j.id): j for j in (await db_session.execute(select(PrintJob))).scalars()}
    for r in rows.values():
        await db_session.refresh(r)
    assert rows[first].status.value == "failed" and rows[first].last_error == "out of paper"
    assert rows[second].status.value == "queued"  # handed back for the next agent


async def test_acks_for_jobs_this_socket_does_not_hold_are_ignored(
    client: httpx.AsyncClient, app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    other = await add_printer(client, world, "Other")
    held = (
        await client.post(f"{base(world)}/printers/{other['id']}/test", headers=world.owner)
    ).json()
    # a job in ANOTHER store, which this agent must never be able to close out
    chai_p = await client.post(
        f"/api/v1/stores/{world.other_store.id}/printers",
        json={"name": "Chai", "connection": "lan", "target": "1.1.1.1"},
        headers=world.other_store_owner,
    )
    foreign = (
        await client.post(
            f"/api/v1/stores/{world.other_store.id}/printers/{chai_p.json()['id']}/test",
            headers=world.other_store_owner,
        )
    ).json()
    created = await pair(client, world)
    ws, task = await run(app, {"token": created["token"]})
    frames = [(await ws.next("job"))["job"]["job_id"]]
    assert frames == [held["id"]]  # only its own store's job
    ws.send({"type": "printed", "job_id": foreign["id"]})
    ws.send({"type": "printed", "job_id": "not-a-uuid"})
    ws.send("garbage")
    await asyncio.sleep(0.3)
    await stop(ws, task)
    row = await db_session.get(PrintJob, uuid.UUID(foreign["id"]))
    await db_session.refresh(row)
    assert row is not None and row.status.value == "queued"


async def test_detected_printers_are_reported_listed_and_merged_by_connection(
    client: httpx.AsyncClient, app: FastAPI, world: World
) -> None:
    created = await pair(client, world)
    ws, task = await run(app, {"token": created["token"]})
    await ws.next("ready")
    ws.send(
        {
            "type": "printers",
            "items": [
                {
                    "key": "q:POS-80",
                    "name": "POS-80 Thermal",
                    "connection": "system",
                    "target": "POS-80",
                    "driver": "Generic / Text Only",
                    "is_default": True,
                },
                {
                    "key": "q:Laser",
                    "name": "Office Laser",
                    "connection": "system",
                    "target": "Laser",
                },
                {
                    "key": "usb:/dev/usb/lp0",
                    "name": "USB printer",
                    "connection": "usb",
                    "target": "/dev/usb/lp0",
                },
                {"key": "bad", "name": "no target", "connection": "system"},
                {"key": "x", "name": "x", "connection": "telepathy", "target": "x"},
            ],
        }
    )
    await asyncio.sleep(0.3)
    ws.send(
        {
            "type": "printers",
            "scope": "lan",
            "items": [
                {
                    "key": "lan:192.168.1.50",
                    "name": "Network printer 192.168.1.50",
                    "connection": "lan",
                    "target": "192.168.1.50:9100",
                }
            ],
        }
    )
    await asyncio.sleep(0.3)
    await stop(ws, task)
    r = await client.get(f"{base(world)}/detected-printers", headers=world.owner)
    got = {d["key"]: d for d in r.json()}
    assert set(got) == {"q:POS-80", "q:Laser", "usb:/dev/usb/lp0", "lan:192.168.1.50"}
    assert got["q:POS-80"]["likely_thermal"] is True and got["q:POS-80"]["is_default"] is True
    assert got["q:Laser"]["likely_thermal"] is False
    assert got["q:POS-80"]["agent_name"] == "PC"
    # a sibling store sees none of it
    other = await client.get(
        f"/api/v1/stores/{world.other_store.id}/detected-printers", headers=world.other_store_owner
    )
    assert other.json() == []
    assert (
        await client.get(f"{base(world)}/detected-printers", headers=world.staff)
    ).status_code == 403


async def test_scan_request_reaches_the_agent_once(
    client: httpx.AsyncClient, app: FastAPI, world: World
) -> None:
    created = await pair(client, world)
    aid = created["agent"]["id"]
    r = await client.post(f"{base(world)}/print-agents/{aid}/scan", headers=world.owner)
    assert r.status_code == 202 and r.json() == {"requested": True}
    assert (
        await client.post(f"{base(world)}/print-agents/{aid}/scan", headers=world.staff)
    ).status_code == 403
    ws, task = await run(app, {"token": created["token"]})
    await ws.next("ready")
    await ws.next("scan_lan")
    await asyncio.sleep(0.3)
    await stop(ws, task)
    types = []
    while not ws.sent.empty():
        types.append(ws.sent.get_nowait()["type"])
    assert "scan_lan" not in types  # asked once, not every poll


# ---------- the queue itself ----------


async def test_lease_attempt_cap_and_inactive_printers(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    printer = await add_printer(client, world)
    jid = uuid.UUID(
        (
            await client.post(f"{base(world)}/printers/{printer['id']}/test", headers=world.owner)
        ).json()["id"]
    )
    queue = PrintQueue(db_session)
    assert len(await queue.claim(world.store.id)) == 1
    assert await queue.claim(world.store.id) == []  # leased
    await db_session.execute(
        update(PrintJob).values(sent_at=datetime.now(UTC) - timedelta(seconds=300))
    )
    again = await queue.claim(world.store.id)
    assert len(again) == 1 and again[0]["attempt"] == 2  # lease expired: handed out again
    await queue.mark_failed(world.store.id, jid, "jam")
    await db_session.execute(
        update(PrintJob).values(
            sent_at=datetime.now(UTC) - timedelta(seconds=300), attempts=MAX_ATTEMPTS
        )
    )
    assert await queue.claim(world.store.id) == []  # given up after the cap

    await db_session.execute(update(PrintJob).values(attempts=0, status="queued"))
    await client.patch(
        f"{base(world)}/printers/{printer['id']}", json={"is_active": False}, headers=world.owner
    )
    assert await queue.claim(world.store.id) == []  # a switched-off printer prints nothing
    other = await queue.claim(world.other_store.id)
    assert other == []


async def test_ack_is_idempotent(
    client: httpx.AsyncClient, world: World, db_session: AsyncSession
) -> None:
    printer = await add_printer(client, world)
    jid = uuid.UUID(
        (
            await client.post(f"{base(world)}/printers/{printer['id']}/test", headers=world.owner)
        ).json()["id"]
    )
    queue = PrintQueue(db_session)
    await queue.claim(world.store.id)
    await queue.mark_printed(world.store.id, jid)
    job = await db_session.get(PrintJob, jid)
    assert job is not None
    first_ack = job.acked_at
    await queue.mark_printed(world.store.id, jid)
    await queue.mark_printed(world.other_store.id, jid)  # a different store cannot touch it
    await db_session.refresh(job)
    assert job.acked_at == first_ack and job.status.value == "printed"
