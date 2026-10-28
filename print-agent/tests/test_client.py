"""The socket loop: what the agent sends, prints, and refuses to print twice.

Driven against a fake server rather than the real one. The backend already covers its
half of this socket (`backend/tests/test_ws_print_agent.py`); what is covered nowhere
until here is the agent's own decisions -- that an already-printed job is acked rather
than reprinted, that a failed write is not recorded as printed, and that the socket
closing leaves neither a half-finished print nor a task waiting forever.

`FakeServer` speaks only what `client.py` uses of a websockets connection: `send`,
`recv` and iteration. It is not a mock of that library, deliberately -- a mock would let
a change in how we call it pass while the real connection broke.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from threading import Event

import pytest
import websockets

from print_agent import __version__, transports
from print_agent.client import Agent, Rejected, await_ready, job_width, probe
from print_agent.config import Config

pytestmark = pytest.mark.ws

JOB = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def ticket_job(job_id: str = JOB, **overrides) -> dict:
    job = {
        "job_id": job_id,
        "printer_id": "33333333-3333-3333-3333-333333333333",
        "printer_name": "Kitchen pass",
        "connection": "usb",
        "target": "/dev/usb/lp0",
        "kind": "ticket",
        "attempt": 1,
        "payload": {
            "kind": "ticket",
            "token": "042",
            "table_label": "G01",
            "origin": "qr",
            "kitchen": "Main kitchen",
            "items": [{"name": "Paneer Tikka", "quantity": 2, "note": None}],
        },
    }
    job.update(overrides)
    return job


def ready() -> dict:
    return {"v": 1, "type": "ready", "agent_id": "44444444-4444-4444-4444-444444444444"}


def job_frame(job: dict) -> dict:
    return {"v": 1, "type": "job", "job": job}


class FakeServer:
    """The frames a server would send, and a record of what the agent sent back.

    The first frame goes out through `recv`, which is what `_await_ready` reads; the
    rest arrive by iteration, which is the job stream. Iteration ending stands in for
    the server closing the connection -- the case that would otherwise leave the printer
    task waiting on a queue nothing will ever fill.

    An empty script is therefore also the *refused* case: the token send succeeds, and
    the read that should have brought `ready` finds the socket gone. That is exactly
    what a revoked credential looks like from here, since the server closes with a
    policy code and sends nothing.
    """

    #: How long to hold the socket open waiting for the reports we expect. Only reached
    #: when a test's expectation is wrong, so it is a diagnostic timeout rather than a
    #: wait anything normally spends time in -- except the deliberate stall test, whose
    #: own print timeout is a second.
    DEADLINE = 5.0

    def __init__(self, frames: list[dict] | None = None, expect: int | None = None) -> None:
        self._frames = list(frames or [])
        self.sent: list[dict] = []
        #: Reports to wait for before hanging up. Defaults to the number of scripted
        #: jobs that could produce one -- a frame with no `job_id` cannot be acked, so
        #: it is not counted.
        self._expect = (
            expect
            if expect is not None
            else sum(
                1
                for frame in self._frames
                if frame.get("type") == "job"
                and isinstance(frame.get("job"), dict)
                and frame["job"].get("job_id")
            )
        )
        #: Set once the job stream has run out, so a test can wait for the agent to have
        #: consumed everything instead of sleeping and hoping.
        self.drained = asyncio.Event()

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        if not self._frames:
            # A revoked credential is closed with the policy code and nothing else,
            # which is the only close `await_ready` may read as "refused".
            raise websockets.exceptions.ConnectionClosedError(
                websockets.frames.Close(1008, ""), None
            )
        return json.dumps(self._frames.pop(0))

    async def __aiter__(self):
        while self._frames:
            yield json.dumps(self._frames.pop(0))
            # Yield to the printer task between frames, so a batch arrives the way the
            # server sends it: several frames queued before any of them is printed.
            await asyncio.sleep(0)

        # Then hold the socket open until the jobs have been reported on, because that
        # is what a real server does -- it sends a batch and goes on waiting. Ending the
        # iteration here instead is what the agent treats as the socket closing, and it
        # then drops whatever is still queued: correct in production, where the jobs
        # cannot be acked anyway and the lease hands them back, but as a *fake* it would
        # mean no test could ever see the second job of a batch print.
        deadline = asyncio.get_running_loop().time() + self.DEADLINE
        while len(self.reports()) < self._expect:
            if asyncio.get_running_loop().time() > deadline:
                break
            await asyncio.sleep(0.005)
        self.drained.set()

    # --- what the agent sent, by kind ---

    def reports(self) -> list[dict]:
        return [f for f in self.sent if f.get("type") in ("printed", "failed")]

    def acked(self, job_id: str) -> bool:
        return any(f.get("type") == "printed" and f.get("job_id") == job_id for f in self.sent)

    def failed(self, job_id: str) -> dict | None:
        for frame in self.sent:
            if frame.get("type") == "failed" and frame.get("job_id") == job_id:
                return frame
        return None


class Printer:
    """Stands in for `transports.send`, recording what it was asked to print.

    A recorder rather than a real device, because what these tests are about is whether
    a write happened and how many times; `test_transports.py` covers the bytes arriving.

    `started` and `block` are `threading.Event`, not the asyncio kind: this is called
    inside `asyncio.to_thread`, so an asyncio event would be touched from the wrong
    thread.
    """

    def __init__(self) -> None:
        self.jobs: list[tuple[str, str, bytes]] = []
        self.error: Exception | None = None
        self.block: Event | None = None
        self.started = Event()
        self.overlapped = False
        self._busy = False

    def __call__(self, connection: str, target: str, data: bytes, *, timeout: float):
        if self._busy:
            # Two writes to one device interleave into a single unreadable slip, so an
            # overlap is a bug rather than merely slow.
            self.overlapped = True
        self._busy = True
        self.started.set()
        try:
            if self.block is not None:
                self.block.wait(timeout=5)
            if self.error is not None:
                raise self.error
            self.jobs.append((connection, target, data))
        finally:
            self._busy = False

    @property
    def count(self) -> int:
        return len(self.jobs)


@pytest.fixture
def printer(monkeypatch) -> Printer:
    fake = Printer()
    monkeypatch.setattr(transports, "send", fake)
    return fake


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        url="ws://localhost:8000/ws/print-agent",
        token="agent.secret",
        paper_width=32,
        # Short, so the stall test does not spend twenty seconds proving itself.
        print_timeout=1.0,
        state_dir=tmp_path,
    )


@pytest.fixture
def agent(config: Config) -> Agent:
    return Agent(config)


# --- Handshake -----------------------------------------------------------------------


async def test_the_token_is_the_first_thing_sent(agent: Agent, printer: Printer):
    """With the agent's version and nothing that names a store.

    An agent does not choose what it receives: it gets the jobs of the store its credential
    belongs to."""
    server = FakeServer([ready()])
    await agent.serve(server)

    assert server.sent[0] == {"token": "agent.secret", "version": __version__}


async def test_a_refused_credential_says_which_screen_reissues_it(agent: Agent, printer: Printer):
    """The server closes with one policy code for malformed, unknown, revoked and
    wrong-secret alike -- deliberately, so the close code cannot be used to sort real
    agent ids from invented ones. There is nothing to distinguish here, so the message
    says the only useful thing.
    """
    with pytest.raises(Rejected, match="Printing > Print agents"):
        await agent.serve(FakeServer([]))


async def test_a_frame_that_is_not_ready_ends_the_connection(agent: Agent, printer: Printer):
    """Rather than ignored while the agent waits for jobs that are never coming. It is
    connection trouble to retry, not a refusal: only the policy close says refused."""
    with pytest.raises(ConnectionError, match="ready"):
        await agent.serve(FakeServer([{"v": 1, "type": "heartbeat"}]))


async def test_a_server_that_never_answers_is_not_waited_on_forever(
    agent: Agent, printer: Printer, monkeypatch
):
    """A socket that connects and then says nothing is a real failure -- a proxy that
    accepted the connection and cannot reach the app behind it. Without this the agent
    would sit there looking connected.
    """
    monkeypatch.setattr("print_agent.client.READY_TIMEOUT_SECONDS", 0.05)

    class Silent(FakeServer):
        async def recv(self) -> str:
            await asyncio.sleep(10)
            raise AssertionError("should have timed out")

    with pytest.raises(TimeoutError, match="in time"):
        await agent.serve(Silent())


# --- Printing ------------------------------------------------------------------------


async def test_a_job_is_printed_and_acked(agent: Agent, printer: Printer):
    server = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(server)

    assert printer.count == 1
    connection, target, data = printer.jobs[0]
    assert (connection, target) == ("usb", "/dev/usb/lp0")
    assert b"Paneer Tikka" in data
    assert server.acked(JOB)


async def test_the_configured_paper_width_is_what_gets_rendered(config: Config, printer: Printer):
    """A 48-column slip on 58mm paper wraps into mush, so this is not cosmetic.

    Compared against the same job at the default width rather than decoded: more lines
    at 20 columns than at 32 is only possible if the setting reached the renderer, and
    it needs no ESC/POS parser to establish.
    """
    long_item = ticket_job(
        payload={
            "kind": "ticket",
            "token": "042",
            "table_label": "G01",
            "origin": "qr",
            "items": [
                {
                    "name": "Chicken Biryani Family Pack With Extra Raita",
                    "quantity": 2,
                    "note": None,
                }
            ],
        }
    )

    await Agent(config).serve(FakeServer([ready(), job_frame(long_item)]))
    wide = printer.jobs[-1][2]

    narrow_config = dataclasses.replace(config, paper_width=20)
    await Agent(narrow_config).serve(
        FakeServer([ready(), job_frame(ticket_job(OTHER, payload=long_item["payload"]))])
    )
    narrow = printer.jobs[-1][2]

    assert narrow.count(b"\n") > wide.count(b"\n")


async def test_a_batch_is_printed_one_job_at_a_time(agent: Agent, printer: Printer):
    """The printers are physical. Two overlapping writes to one device produce a single
    slip of interleaved bytes, so a worker pool would mostly be a way to corrupt slips
    faster.
    """
    jobs = [ticket_job(f"{index:032d}") for index in range(5)]
    server = FakeServer([ready(), *[job_frame(job) for job in jobs]])

    await agent.serve(server)

    assert printer.count == 5
    assert printer.overlapped is False
    assert len(server.reports()) == 5


async def test_the_server_is_asked_for_more_work_after_each_job(agent: Agent, printer: Printer):
    """Rather than waiting out the server's three-second poll. At a dinner rush that is
    the difference between a slip being on the pass before the next order is taken.
    """
    server = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(server)

    assert {"type": "pull"} in server.sent
    # After the report, not instead of it: the pull asks for the next batch.
    printed = next(f for f in server.sent if f.get("type") == "printed")
    assert server.sent.index({"type": "pull"}) > server.sent.index(printed)


async def test_a_bill_prints_its_bill_wording(agent: Agent, printer: Printer):
    job = ticket_job(
        kind="bill",
        payload={
            "kind": "bill",
            "token": "042",
            "table_label": "G01",
            "origin": "qr",
            "copy_number": 2,
            "lines": [
                {
                    "name": "Thali",
                    "quantity": 1,
                    "unit_price": "120.00",
                    "line_total": "120.00",
                    "note": None,
                }
            ],
            "subtotal": "120.00",
            "discount_amount": "0.00",
            "total": "120.00",
        },
    )
    await agent.serve(FakeServer([ready(), job_frame(job)]))

    _, _, data = printer.jobs[0]
    assert b"BILL" in data
    assert b"COPY 2" in data


# --- Idempotency (AGENT.md rule 9) ---------------------------------------------------


async def test_a_redelivered_job_is_acked_without_being_reprinted(agent: Agent, printer: Printer):
    """AGENT.md rule 9, and the most important test in this app.

    The server redelivers whenever an ack was lost, which it cannot tell apart from a
    job that never printed. Both halves of the answer matter: not printing is the
    guarantee, and acking anyway is what stops the server handing it back every time the
    lease expires until the attempt cap gives up on a job nobody ever resolves.
    """
    server = FakeServer([ready(), job_frame(ticket_job()), job_frame(ticket_job())])
    await agent.serve(server)

    assert printer.count == 1
    assert len([f for f in server.reports() if f["job_id"] == JOB]) == 2


async def test_the_record_survives_a_reconnect(agent: Agent, printer: Printer):
    """The disconnect is what loses the ack, so a record that did not outlive the
    connection would forget exactly when it was needed."""
    await agent.serve(FakeServer([ready(), job_frame(ticket_job())]))
    assert printer.count == 1

    second = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(second)

    assert printer.count == 1
    assert second.acked(JOB)


async def test_the_record_survives_the_process(config: Config, printer: Printer):
    """A reboot mid-job is the ordinary way an ack is lost on a hotel PC."""
    await Agent(config).serve(FakeServer([ready(), job_frame(ticket_job())]))
    assert printer.count == 1

    restarted = Agent(config)
    restarted.printed.load()  # what a new process does before its first connection
    server = FakeServer([ready(), job_frame(ticket_job())])
    await restarted.serve(server)

    assert printer.count == 1
    assert server.acked(JOB)


async def test_run_forever_loads_the_record_before_connecting(config: Config, printer: Printer):
    """Otherwise the first batch after a restart reprints everything the server still
    holds -- which is every job whose ack the restart lost."""
    seeded = Agent(config)
    seeded.printed.load()
    seeded.printed.record(JOB)

    fresh = Agent(config)
    assert JOB not in fresh.printed  # nothing read yet

    class StopsImmediately(Agent):
        async def run_once(self) -> None:
            raise asyncio.CancelledError

    loading = StopsImmediately(config)
    with pytest.raises(asyncio.CancelledError):
        await loading.run_forever()
    assert JOB in loading.printed


async def test_a_job_that_failed_to_print_is_printed_when_it_comes_back(
    agent: Agent, printer: Printer
):
    """The other half of rule 9, and why the record is written *after* the write.

    A failed job must not be remembered as printed, or the retry the server is designed
    to send would be acked with no paper ever coming out -- the one failure a kitchen
    cannot detect.
    """
    printer.error = transports.TransportError("out of paper")
    server = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(server)

    assert server.failed(JOB) is not None
    assert JOB not in agent.printed

    printer.error = None
    retry = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(retry)

    assert printer.count == 1
    assert retry.acked(JOB)


async def test_two_different_jobs_are_both_printed(agent: Agent, printer: Printer):
    """The dedupe is by job id and nothing else: two identical tickets for one table are
    two orders, and a kitchen needs both slips."""
    server = FakeServer([ready(), job_frame(ticket_job()), job_frame(ticket_job(OTHER))])
    await agent.serve(server)

    assert printer.count == 2


# --- Failures ------------------------------------------------------------------------


async def test_a_printer_that_refuses_is_reported_with_its_reason(agent: Agent, printer: Printer):
    """Reported, so it lands on the admin printers screen against this printer -- the
    whole path by which a hotel finds out a printer is out of paper."""
    printer.error = transports.TransportError("/dev/usb/lp0 would not accept the job")
    server = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(server)

    failure = server.failed(JOB)
    assert failure is not None
    assert "lp0" in failure["error"]


@pytest.mark.parametrize("missing", [None, "", "   "])
async def test_a_printer_with_no_address_is_refused_before_the_write(
    agent: Agent, printer: Printer, missing
):
    """`target` is nullable in the `printers` table, so this frame is a real one.

    An admin who registers a printer and has not yet typed its address -- or who clears
    the field -- produces a job whose `target` is JSON `null`. It must not be handed to
    a transport, because `str(None)` is the string `"None"`: for `usb` or `bluetooth`
    that is a *relative file of that name*, which `send_device` creates and writes the
    slip into quite successfully. The job would be recorded and acked, and the printers
    screen would show a slip that no paper ever carried -- the one failure a kitchen
    cannot detect, and exactly what the record-then-ack order exists to prevent.
    """
    server = FakeServer([ready(), job_frame(ticket_job(target=missing))])
    await agent.serve(server)

    assert printer.count == 0, "a job with no address must not reach a transport"

    failure = server.failed(JOB)
    assert failure is not None
    # Names the printer and the remedy: "no address" alone would send an admin
    # looking for a dead printer rather than to the field they left empty.
    assert "Kitchen pass" in failure["error"]
    assert "Printing > Print agents" in failure["error"]

    # Not recorded, so correcting the address and letting the server redeliver still
    # prints the slip. Recording it here would lose the job permanently.
    assert JOB not in agent.printed


async def test_a_printer_that_stalls_is_given_up_on_and_reported(agent: Agent, printer: Printer):
    """A printer can accept a connection and then never read a byte.

    Failed is the truthful report: we do not know whether paper came out, and a hotel
    would rather reprint than believe a slip exists.
    """
    printer.block = Event()  # never set until the end of the test
    server = FakeServer([ready(), job_frame(ticket_job())])
    try:
        await agent.serve(server)

        failure = server.failed(JOB)
        assert failure is not None
        assert "in time" in failure["error"]
        assert JOB not in agent.printed
    finally:
        # Releases the abandoned thread, which the loop would otherwise wait on when it
        # shuts its executor down.
        printer.block.set()


async def test_a_stalled_write_that_lands_later_is_not_printed_a_second_time(
    agent: Agent, printer: Printer
):
    """A slow printer takes the bytes *after* the timeout; the redelivery must not print again.

    The timeout abandons the wait, not the write: `to_thread` cannot be cancelled, so the
    thread keeps going and paper comes out whenever the printer finally reads. The job was
    reported failed and never recorded, so the server hands it back and a second slip
    comes out -- the same bill twice, with no COPY line because it is the same job.

    The second delivery here arrives while the first write is still stuck, which is the
    worst case: starting a second write would put two of them against one printer.
    """
    printer.block = Event()
    server = FakeServer([ready(), job_frame(ticket_job()), job_frame(ticket_job())])
    try:
        await agent.serve(server)
        assert printer.count == 0  # still stuck: nothing has come out yet
    finally:
        printer.block.set()  # the printer finally takes the bytes

    for _ in range(100):  # let the abandoned write(s) finish
        if printer.count:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)  # long enough for a second write to land if one was started

    assert printer.count == 1
    assert printer.overlapped is False
    # The late write is the evidence paper came out, so a later redelivery is acked
    # from the record instead of printing again.
    assert JOB in agent.printed


async def test_an_unexpected_write_error_does_not_poison_the_jobs_retries(
    agent: Agent, printer: Printer
):
    """A write that raises something no transport is meant to raise must not leave its
    failed result behind: after a reconnect the server hands the job back, and waiting on
    the old failure would crash the agent again every time, until it was restarted."""
    printer.error = ValueError("the driver blew up")
    with pytest.raises(ValueError):
        await agent.serve(FakeServer([ready(), job_frame(ticket_job())]))

    printer.error = None
    server = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(server)

    assert server.acked(JOB)
    assert printer.count == 1


async def test_a_job_this_agent_cannot_render_is_reported_rather_than_dropped(
    agent: Agent, printer: Printer
):
    """A rendering gap is a bug on our side, and this is how it becomes visible instead
    of becoming a slip that never appears."""
    server = FakeServer([ready(), job_frame(ticket_job(kind="receipt", payload={}))])
    await agent.serve(server)

    failure = server.failed(JOB)
    assert failure is not None
    assert "receipt" in failure["error"]
    assert printer.count == 0


async def test_an_unknown_connection_kind_is_reported_against_the_job(config: Config):
    """Not raised through the socket loop, where an admin would see an agent that keeps
    reconnecting and no reason why.

    Deliberately without the `printer` fixture: this needs the real dispatcher, which
    refuses the kind before any device is touched.
    """
    server = FakeServer([ready(), job_frame(ticket_job(connection="parallel"))])
    await Agent(config).serve(server)

    failure = server.failed(JOB)
    assert failure is not None
    assert "unknown connection" in failure["error"]


async def test_a_long_error_is_truncated_before_it_is_sent(agent: Agent, printer: Printer):
    """The server drops frames over 16KB, and a dropped report is a lost ack -- which is
    a slip the lease hands back and the kitchen sees twice."""
    printer.error = transports.TransportError("x" * 5000)
    server = FakeServer([ready(), job_frame(ticket_job())])
    await agent.serve(server)

    failure = server.failed(JOB)
    assert failure is not None
    assert len(failure["error"]) <= 500


async def test_a_job_with_no_id_is_left_alone(agent: Agent, printer: Printer):
    """Nothing can be acked for it, so printing it would produce a slip the server goes
    on redelivering forever."""
    job = ticket_job()
    del job["job_id"]
    server = FakeServer([ready(), job_frame(job)])
    await agent.serve(server)

    assert printer.count == 0
    assert server.reports() == []


# --- Frames the agent should shrug at ------------------------------------------------


@pytest.mark.parametrize(
    "frame",
    [
        {"v": 1, "type": "heartbeat"},
        {"v": 1, "type": "something-new"},
        {"v": 1, "type": "job"},
        {"v": 1, "type": "job", "job": "not an object"},
        {"v": 1},
    ],
)
async def test_a_frame_the_agent_cannot_use_does_not_stop_it_printing(
    agent: Agent, printer: Printer, frame: dict
):
    """The server and the agent are deployed separately -- a hotel PC updates when
    somebody gets round to it -- so an agent that fell over on a frame from a newer
    server would turn every deploy into a support call."""
    server = FakeServer([ready(), frame, job_frame(ticket_job())])
    await agent.serve(server)

    assert printer.count == 1
    assert server.acked(JOB)


async def test_a_frame_that_is_not_json_does_not_stop_it_printing(agent: Agent, printer: Printer):
    class Noisy(FakeServer):
        async def __aiter__(self):
            yield "{not json"
            yield json.dumps(job_frame(ticket_job()))
            self.drained.set()

    server = Noisy([ready()])
    await agent.serve(server)

    assert server.acked(JOB)


# --- Shutdown ------------------------------------------------------------------------


async def test_the_socket_closing_ends_the_loop(agent: Agent, printer: Printer):
    """Rather than leaving the printer task waiting on a queue nothing will fill.

    This is the bug that would look worst in production: an agent that is connected, logs
    nothing and prints nothing, because one of its two tasks ended and the other was
    blocked forever. The timeout is the assertion.
    """
    server = FakeServer([ready()])
    await asyncio.wait_for(agent.serve(server), timeout=2)
    assert server.drained.is_set()


async def test_a_job_already_being_printed_is_finished_rather_than_abandoned(
    agent: Agent, printer: Printer
):
    """Cancelling mid-write would abandon a job whose bytes the printer may already have
    taken -- and since the record is written after the write, the reconnect would print
    it again. Letting it finish costs at most one print timeout and keeps the record
    truthful.

    The server here waits for the write to have started before hanging up, which is the
    only way to test the in-flight case: a close that lands before the printer's first
    loop check finds nothing in progress, and dropping the job then is correct, because
    nothing could be acked for it anyway.
    """
    printer.block = Event()

    class HangsUpMidJob(FakeServer):
        async def __aiter__(self):
            yield json.dumps(job_frame(ticket_job()))
            # `started` is a threading.Event, set from inside the write thread, so it is
            # waited on in a thread of its own rather than polled from the loop.
            await asyncio.to_thread(printer.started.wait, 5)
            self.drained.set()

    server = HangsUpMidJob([ready()])
    serving = asyncio.create_task(agent.serve(server))

    await asyncio.sleep(0.05)
    printer.block.set()
    await asyncio.wait_for(serving, timeout=3)

    assert printer.count == 1
    assert JOB in agent.printed


async def test_a_report_on_a_closed_socket_does_not_lose_the_record(agent: Agent, printer: Printer):
    """The paper is out, so what matters is the local record -- the reconnect acks from
    it. Raising here instead would lose the remaining jobs in the queue for no benefit.
    """

    class HangsUp(FakeServer):
        async def send(self, raw: str) -> None:
            message = json.loads(raw)
            if message.get("type") == "printed":
                raise websockets.exceptions.ConnectionClosedOK(None, None)
            self.sent.append(message)

        async def __aiter__(self):
            yield json.dumps(job_frame(ticket_job()))
            # Waiting for a report here would wait forever: this server refuses the one
            # it is about to be sent, which is the whole point of the test. So it hangs
            # up as soon as the write has started instead.
            await asyncio.to_thread(printer.started.wait, 5)
            self.drained.set()

    server = HangsUp([ready()])
    await agent.serve(server)

    assert printer.count == 1
    assert JOB in agent.printed


# --- Reconnecting --------------------------------------------------------------------


async def test_a_lost_connection_is_retried(config: Config, monkeypatch):
    """The common disconnect is a flaky hotel uplink that is back in a second."""
    monkeypatch.setattr("print_agent.client.MIN_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr("print_agent.client.MAX_BACKOFF_SECONDS", 0.01)

    attempts = 0

    class Flaky(Agent):
        async def run_once(self) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("network unreachable")
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await Flaky(config).run_forever()
    assert attempts == 3


async def test_a_server_that_closed_cleanly_is_dialled_again(config: Config, monkeypatch):
    """A clean close is a deploy, not an error -- and an agent that stopped on one would
    need somebody to walk to the PC after every release."""
    monkeypatch.setattr("print_agent.client.MIN_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr("print_agent.client.MAX_BACKOFF_SECONDS", 0.01)

    attempts = 0

    class Closes(Agent):
        async def run_once(self) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                return  # served, then the server hung up
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await Closes(config).run_forever()
    assert attempts == 2


async def test_a_revoked_credential_stops_the_agent_instead_of_looping(config: Config):
    """Reconnecting with the same token gets the same answer forever.

    The exit code is what a service manager reads: restart an agent that lost its
    network, do not restart one whose credential was revoked -- the second would be an
    endless loop of rejected connections with nobody ever told.
    """
    attempts = 0

    class Refused(Agent):
        async def run_once(self) -> None:
            nonlocal attempts
            attempts += 1
            raise Rejected("no")

    # Bounded, because the failure mode this guards against is a *loop*: an agent that
    # swallowed `Rejected` would retry with backoff forever, so an unbounded await here
    # would hang the suite rather than fail it -- and a hanging test says far less than a
    # failing one. The timeout is longer than the first backoff would be, so reaching it
    # means retrying, not slowness.
    with pytest.raises(Rejected):
        await asyncio.wait_for(Refused(config).run_forever(), timeout=3)
    assert attempts == 1


async def test_a_probe_sends_the_token_flagged_as_a_probe_and_returns_the_agent_id():
    server = FakeServer([ready()])

    agent_id = await probe(server, "tok")

    assert agent_id == ready()["agent_id"]
    assert server.sent == [{"token": "tok", "probe": True}]


async def test_a_refused_probe_raises_rejected():
    with pytest.raises(Rejected):
        await probe(FakeServer([]), "tok")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (48, 48),
        (20, 20),
        (96, 96),
        (19, 32),
        (97, 32),
        (None, 32),
        ("48", 32),
        (48.0, 32),
        (True, 32),
    ],
)
def test_a_job_width_is_used_only_when_it_is_a_sane_integer(given, expected):
    """The server's value is trusted only as far as the config file's own is: a
    bool, a float, a string or an out-of-range number falls back to the PC's setting
    instead of rendering a slip 4,000 columns wide."""
    job = {} if given is None else {"paper_width": given}
    assert job_width(job, 32) == expected


async def test_the_printers_own_paper_width_beats_the_pcs_setting(agent: Agent, printer: Printer):
    wide = ticket_job(JOB, paper_width=48)
    narrow = ticket_job(OTHER)  # no paper_width: the PC's 32 applies
    server = FakeServer([ready(), job_frame(wide), job_frame(narrow)])

    await agent.serve(server)

    first, second = (data for _, _, data in printer.jobs)
    assert b"-" * 48 in first
    assert b"-" * 33 not in second
    assert b"-" * 32 in second


async def test_a_bill_whose_logo_is_malformed_still_prints_and_acks(agent: Agent, printer: Printer):
    job = {
        "job_id": JOB,
        "printer_id": "33333333-3333-3333-3333-333333333333",
        "printer_name": "Till",
        "connection": "usb",
        "target": "/dev/usb/lp0",
        "kind": "bill",
        "attempt": 1,
        "payload": {
            "kind": "bill",
            "token": "042",
            "table_label": "G01",
            "origin": "qr",
            "copy_number": 1,
            "lines": [],
            "subtotal": "0.00",
            "discount_amount": "0.00",
            "total": "0.00",
            "header": {
                "logo": {"width": 16, "height": 2, "data": "!!!"},
                "name": "Spice Garden",
            },
        },
    }
    server = FakeServer([ready(), job_frame(job)])

    await agent.serve(server)

    assert printer.count == 1
    assert b"Spice Garden" in printer.jobs[0][2]
    assert server.acked(JOB)


class _Closes:
    """A socket whose first read fails the way `code` says, or hangs."""

    def __init__(self, code: int | None = None, hang: bool = False) -> None:
        self.code, self.hang = code, hang

    async def recv(self):
        if self.hang:
            await asyncio.sleep(60)
        raise websockets.exceptions.ConnectionClosedError(
            websockets.frames.Close(self.code, "") if self.code else None, None
        )


async def test_only_the_policy_close_means_the_credential_was_refused():
    with pytest.raises(Rejected):
        await await_ready(_Closes(1008))


@pytest.mark.parametrize("code", [1011, 1012, 1001, None])
async def test_any_other_close_before_ready_is_a_hiccup_not_a_refusal(code):
    """A deploy, a database blip or a dropped uplink must be retried, not turned into
    exit 3 -- which both supervisors read as "stay stopped for good"."""
    with pytest.raises(websockets.ConnectionClosed) as caught:
        await await_ready(_Closes(code))
    assert not isinstance(caught.value, Rejected)


async def test_a_server_too_slow_to_say_ready_is_a_hiccup_not_a_refusal(monkeypatch):
    monkeypatch.setattr("print_agent.client.READY_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(TimeoutError):
        await await_ready(_Closes(hang=True))


async def test_an_unexpected_first_frame_is_a_hiccup_not_a_refusal():
    class Odd:
        async def recv(self):
            return json.dumps({"v": 1, "type": "heartbeat"})

    with pytest.raises(ConnectionError):
        await await_ready(Odd())


async def test_cancelling_a_connection_takes_its_reader_and_printer_with_it(
    caplog,
) -> None:
    """An update cancels the connection loop; nothing may be left running or unreported."""
    from print_agent import client

    agent = client.Agent(Config(url="ws://x/ws/print-agent", token="t", auto_update=False))

    class Socket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, data: str) -> None:
            self.sent.append(data)
            if "token" in data:
                return

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)

    async def ready(_socket) -> dict:
        return {"type": "ready", "agent_id": "a"}

    socket = Socket()
    original = client.await_ready
    client.await_ready = ready
    try:
        task = asyncio.create_task(agent.serve(socket))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        client.await_ready = original

    await asyncio.sleep(0.05)
    leftovers = [
        t
        for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and ("_read" in repr(t) or "_print" in repr(t))
    ]
    assert leftovers == []
    assert "never retrieved" not in caplog.text
