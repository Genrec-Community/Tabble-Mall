"""The socket, the loop, and the decision to print or not.

**The agent dials out.** There is no inbound port, no port forwarding and no static IP
at the store (`docs/ARCHITECTURE.md` § KOT printing). A restaurant's network is a
domestic router someone else installed, so the only connection that can be relied on is
the one we make.

**Reading and printing are separate tasks.** A printer that is out of paper can hold a
write for the whole print timeout, and during that time the socket still has to be
drained -- the server sends a heartbeat every three seconds and a batch of up to twenty
jobs at once. Printing inline would leave those unread, and a job sitting unread for
longer than the server's lease is a job handed to a sibling agent while we still hold
it. So a reader task queues jobs and one worker prints them, strictly one at a time,
because the printers are physical and two concurrent writes to one device interleave
into confetti.

**Reports are sent as each job finishes, not batched.** An ack is the only evidence that
paper came out; a batch of acks lost to a dropped socket is a tray of slips the kitchen
sees twice.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import ssl
from typing import Any, Final

import websockets
from websockets.asyncio.client import connect

from . import __version__, detect, render, transports
from .config import (
    MAX_BACKOFF_SECONDS,
    MAX_PAPER_WIDTH,
    MIN_BACKOFF_SECONDS,
    MIN_PAPER_WIDTH,
    Config,
)
from .store import PrintedJobs

logger = logging.getLogger(__name__)

#: How long to wait for `ready` after sending the token. The server closes with a
#: policy code and says nothing on a bad credential, so this timeout is also how a
#: rejected agent notices it was rejected.
READY_TIMEOUT_SECONDS: Final = 15.0

#: Our own keepalive, independent of the server's heartbeat. Detects a store uplink
#: that dropped without either side seeing a FIN -- the common failure on consumer
#: routers, where a socket stays "open" for minutes with nothing behind it.
PING_INTERVAL_SECONDS: Final = 20.0
PING_TIMEOUT_SECONDS: Final = 20.0

#: Room for one server batch plus a little. Not unbounded: if the queue is growing, the
#: printer is slower than the kitchen orders, and the useful thing is for jobs to stay
#: on the server -- where the lease hands them to another agent and the admin can see
#: them -- rather than accumulating invisibly in this process.
QUEUE_LIMIT: Final = 32

#: How often the PC's printer list is re-checked (only changes are sent).
REPORT_INTERVAL_SECONDS: Final = 60.0

#: The whole of `--check`: dial, probe, hang up. Longer than `READY_TIMEOUT_SECONDS`
#: so a slow handshake is reported as the server not answering rather than as this
#: outer timer firing first.
CHECK_TIMEOUT_SECONDS: Final = 30.0


#: The close code the server uses, for every kind of refusal alike (RFC 6455 1008).
POLICY_CLOSE_CODE: Final = 1008


class Rejected(Exception):
    """The server refused this credential.

    Distinguished from every other disconnect because it is the one that will not fix
    itself: reconnecting with the same token gets the same answer forever. The loop
    stops and says what to do about it.
    """


def _ssl_context(config: Config) -> ssl.SSLContext | bool | None:
    """TLS settings for the dial.

    `None` for a plain `ws://` URL, which is the dev case. Verification off is offered
    because a store behind a self-signed reverse proxy is a real deployment and the
    alternative is an admin who cannot start the agent at all -- but it is a
    deliberate switch in the config file, never a fallback after a handshake failure.
    """
    if not config.url.startswith("wss://"):
        return None
    if config.verify_tls:
        return ssl.create_default_context()

    logger.warning("TLS certificate verification is OFF for %s", config.url)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def job_width(job: dict[str, Any], default: int) -> int:
    """The line width to render one job at: the printer's own, else the PC's.

    The printer's width arrives with the job (the admin sets it per printer), so a
    counter printer on 80 mm paper and a kitchen printer on 58 mm can share one agent
    or sit on different PCs. Anything that is not a plain integer in range -- a bool,
    a float, a string, `null`, a number from a server that has gone wrong -- falls back
    to `default`, the same way a job from a server that predates the field does.
    """
    value = job.get("paper_width")
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and MIN_PAPER_WIDTH <= value <= MAX_PAPER_WIDTH
    ):
        return value
    return default


async def await_ready(socket: Any) -> dict[str, Any]:
    """Wait for the server to confirm the credential, and return its `ready` frame.

    A close with the **policy code** instead of a `ready` frame means refused. The
    server sends that one code for malformed, unknown, revoked and wrong-secret
    alike, deliberately, so there is nothing to distinguish here and the message says
    the only useful thing: that the token needs reissuing from the admin screen.

    Nothing else is a refusal. A timeout, a close with any other code (a deploy, a
    database blip: the server answers 1011/1012) or an unexpected first frame is
    raised as the ordinary connection trouble it is, so the agent retries with backoff
    and `--check` reports "could not reach". Calling those a refusal would exit 3,
    which both supervisors read as "stay stopped for good" -- a PC that stops printing
    because the server restarted once.
    """
    try:
        async with asyncio.timeout(READY_TIMEOUT_SECONDS):
            raw = await socket.recv()
    except TimeoutError:
        raise TimeoutError("server did not answer the credential in time") from None
    except websockets.ConnectionClosed as exc:
        if exc.rcvd is not None and exc.rcvd.code == POLICY_CLOSE_CODE:
            raise Rejected(
                "server refused this credential - pair this PC again under "
                "Printing > Print agents in the store dashboard and paste the new token "
                "into the config"
            ) from None
        raise

    message = _parse(raw)
    if message.get("type") != "ready":
        raise ConnectionError(f"expected a ready frame, got {message.get('type')!r}")
    return message


async def probe(socket: Any, token: str) -> str | None:
    """Ask the server whether it accepts `token`, claiming nothing.

    The `probe` flag tells the server to answer `ready` and stop there. Without it the
    server would hand this socket a batch of queued slips straight after `ready`, and
    each claim spends one of a slip's ten attempts.
    """
    await socket.send(json.dumps({"token": token, "probe": True}))
    message = await await_ready(socket)
    agent_id = message.get("agent_id")
    return agent_id if isinstance(agent_id, str) else None


async def check_credential(config: Config) -> str | None:
    """Dial, probe, hang up. Raises `Rejected`, or a connection error.

    Touches no printer and no job. Against a server that predates the probe flag it
    degrades to an ordinary connection, which is why an installer runs it with the
    agent stopped.
    """
    async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
        async with connect(config.url, ssl=_ssl_context(config), compression=None) as socket:
            return await probe(socket, config.token)


class Agent:
    """One configured agent: connects, prints, reconnects.

    Holds the printed-jobs record across reconnects, which is the point of it being an
    object rather than a function -- a fresh record per connection would reprint
    everything the server redelivers, which is every job whose ack the disconnect lost.
    """

    def __init__(self, config: Config, printed: PrintedJobs | None = None) -> None:
        self.config = config
        self.printed = printed if printed is not None else PrintedJobs(config.printed_log)
        #: The write for each job that has not finished, by job id. A timeout gives up
        #: *waiting*, not writing -- the thread runs on and the printer may still take the
        #: bytes -- so the write is kept here until it ends, and a redelivery of the same
        #: job waits on it instead of starting a second one.
        self._writes: dict[str, asyncio.Future[None]] = {}
        #: Jobs received and not yet reported, so "idle" means nothing is queued or
        #: being written -- the only moment the program may be replaced.
        self._unfinished = 0
        #: Set once the server has confirmed the credential on any connection.
        self._ready = asyncio.Event()
        #: Printers found on this PC, sent to the server so the owner can pick from a list.
        self._detector = detect.Detector()
        self._last_report: str = ""
        self._extras: set[asyncio.Task[None]] = set()

    def idle(self) -> bool:
        """No slip is waiting or being written."""
        return self._unfinished == 0 and not self._writes

    async def run_forever(self) -> None:
        """Run the connection loop until cancelled or the server refuses the credential."""
        await self._connect_forever()

    async def _connect_forever(self) -> None:
        """Connect, serve, reconnect, until cancelled or rejected.

        Backoff is jittered. Not for the server's sake -- there is one agent per store
        PC -- but because the thing that disconnects every agent at once is the server
        restarting, and an unjittered herd arrives during the same second it is still
        opening its own connections.
        """
        self.printed.load()
        logger.info(
            "starting: %s, %d job(s) already recorded as printed",
            self.config.url,
            len(self.printed),
        )

        backoff = MIN_BACKOFF_SECONDS
        while True:
            try:
                await self.run_once()
                # A clean return means the server closed on us. Not an error, but not
                # a reason to hammer either: reset the backoff and dial again.
                backoff = MIN_BACKOFF_SECONDS
                logger.info("server closed the connection - reconnecting")
            except Rejected:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("connection lost (%s) - retrying in %.0fs", exc, backoff)

            await asyncio.sleep(backoff * (0.5 + random.random()))
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def run_once(self) -> None:
        """One connection, from dial to close."""
        async with connect(
            self.config.url,
            ssl=_ssl_context(self.config),
            ping_interval=PING_INTERVAL_SECONDS,
            ping_timeout=PING_TIMEOUT_SECONDS,
            # The agent sends small frames and receives job payloads; neither needs
            # compression, and leaving it off keeps one fewer thing negotiating on a
            # link that is already the unreliable part.
            compression=None,
        ) as socket:
            await self.serve(socket)

    async def serve(self, socket: Any) -> None:
        """Authenticate, then run the reader, the printer and the printer reporter."""
        await socket.send(json.dumps({"token": self.config.token, "version": __version__}))
        await self._await_ready(socket)
        self._last_report = ""
        reporter = asyncio.create_task(self._report_printers(socket))
        self._extras.add(reporter)
        try:
            await self._serve_ready(socket)
        finally:
            for task in list(self._extras):
                task.cancel()
            await asyncio.gather(*self._extras, return_exceptions=True)
            self._extras.clear()

    async def _report_printers(self, socket: Any) -> None:
        """Tell the server which printers this PC has, now and whenever the list changes."""
        while True:
            items = await asyncio.to_thread(lambda: [f.as_dict() for f in self._detector.local()])
            fingerprint = json.dumps(items, sort_keys=True)
            if fingerprint != self._last_report:
                self._last_report = fingerprint
                await self._send(socket, {"type": "printers", "scope": "local", "items": items})
            await asyncio.sleep(REPORT_INTERVAL_SECONDS)

    async def _scan_lan(self, socket: Any) -> None:
        """The dashboard asked for a network scan. Runs on request only."""
        logger.info("scanning the local network for printers")
        items = await asyncio.to_thread(lambda: [f.as_dict() for f in self._detector.scan_lan()])
        await self._send(socket, {"type": "printers", "scope": "lan", "items": items})

    @staticmethod
    async def _send(socket: Any, frame: dict[str, Any]) -> None:
        with contextlib.suppress(websockets.ConnectionClosed):
            await socket.send(json.dumps(frame))

    async def _serve_ready(self, socket: Any) -> None:
        self._unfinished = 0  # a fresh queue: whatever was waiting was handed back

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        closing = asyncio.Event()
        reader = asyncio.create_task(self._read(socket, queue))
        printer = asyncio.create_task(self._print(socket, queue, closing))

        # Raced rather than gathered, because neither ends on its own in the normal
        # case and each ending means something different. The reader returns when the
        # socket closes, and the printer would then wait on an empty queue forever --
        # an agent that looks connected and prints nothing.
        try:
            done, pending = await asyncio.wait(
                (reader, printer), return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            # Cancelled from outside (an update is being installed, which only happens
            # between jobs). Take the two tasks down with us: left running they finish
            # later with nobody to collect their result, and asyncio logs a scary
            # "Task exception was never retrieved" for a perfectly clean exit.
            for task in (reader, printer):
                task.cancel()
            await asyncio.gather(reader, printer, return_exceptions=True)
            raise

        # Asked to stop, not cancelled, and this is the difference between a clean
        # reconnect and a duplicate slip: cancelling mid-write abandons a job whose
        # bytes the printer may already have taken, and since the record is written
        # after the write, the reconnect would print it again. Letting the current job
        # finish costs at most one print timeout and leaves the record correct.
        # Jobs still queued behind it are dropped unprinted, which is right -- the
        # socket is gone, so they could not be acked, and the server hands them back.
        closing.set()
        if printer in pending:
            try:
                await asyncio.wait_for(printer, timeout=self.config.print_timeout + 5)
            except (TimeoutError, asyncio.CancelledError):
                logger.warning("gave up waiting for the job in progress")
        if reader in pending:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader

        for task in {*done, printer}:
            if not task.done() or task.cancelled():
                continue
            try:
                task.result()
            except websockets.ConnectionClosed:
                # Ordinary. Either side may hang up; `run_forever` dials again and the
                # server has already handed our unacked jobs back.
                logger.info("connection closed")

    async def _await_ready(self, socket: Any) -> None:
        """Wait for the server to confirm the credential (see `await_ready`)."""
        message = await await_ready(socket)
        self._ready.set()
        logger.info("paired as agent %s", message.get("agent_id"))

    async def _read(self, socket: Any, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Take frames off the socket and queue the jobs.

        Nothing here touches a printer, so this loop keeps running while a job is being
        written -- which is the whole reason it is a separate task.

        An unknown frame type is ignored rather than fatal. The server and the agent are
        deployed separately: an agent that fell over on a frame from a newer server
        would turn every deploy into a support call.
        """
        async for raw in socket:
            message = _parse(raw)
            kind = message.get("type")

            if kind == "job":
                job = message.get("job")
                if not isinstance(job, dict):
                    logger.warning("job frame with no job object")
                    continue
                self._unfinished += 1
                await queue.put(job)
            elif kind == "heartbeat":
                continue
            elif kind == "scan_lan":
                task = asyncio.create_task(self._scan_lan(socket))
                self._extras.add(task)
                task.add_done_callback(self._extras.discard)
            else:
                logger.debug("ignoring frame type %r", kind)

    async def _print(
        self,
        socket: Any,
        queue: asyncio.Queue[dict[str, Any]],
        closing: asyncio.Event,
    ) -> None:
        """Print queued jobs one at a time and report each.

        Serial by construction. The printers are physical devices and two overlapping
        writes to one of them produce a single slip of interleaved bytes -- and since
        one agent commonly drives one printer, a worker pool would mostly be a way to
        corrupt slips faster.

        After each job, `pull` asks the server for more rather than waiting out its
        three-second poll. That matters at a dinner rush, where the difference is
        whether a slip is on the pass before the next order is taken.

        `closing` is checked between jobs and never during one. It is how the socket
        going away stops this loop without cancelling a write that a printer may have
        already taken bytes from -- see `serve`.
        """
        while not closing.is_set():
            job = await _next(queue, closing)
            if job is None:
                return

            try:
                await self._handle(socket, job)
            finally:
                self._unfinished = max(0, self._unfinished - 1)
            if closing.is_set():
                return
            with contextlib.suppress(websockets.ConnectionClosed):
                await socket.send(json.dumps({"type": "pull"}))

    async def _handle(self, socket: Any, job: dict[str, Any]) -> None:
        """One job: render, write, record, report.

        The order is deliberate and the comments in `store.py` explain why recording
        sits between the write and the report.
        """
        job_id = job.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            logger.warning("job frame with no job_id - nothing can be acked for it")
            return

        if job_id in self.printed:
            # AGENT.md rule 9. Acked anyway, not ignored: an unacked job comes back
            # when the lease expires, ten times, and then stops being retried at all --
            # so silence here is how a store ends up with a job nobody resolves.
            logger.info("job %s already printed - acking without reprinting", job_id)
            await self._report(socket, "printed", job_id)
            return

        try:
            data = render.render(job, width=job_width(job, self.config.paper_width))
        except render.UnknownPayload as exc:
            # Reported, so it lands on the printers screen against this printer. A
            # rendering gap is a bug on our side and this is how it becomes visible
            # instead of becoming a slip that never appears.
            logger.error("cannot render job %s: %s", job_id, exc)
            await self._report(socket, "failed", job_id, error=str(exc))
            return

        connection = str(job.get("connection", ""))
        raw_target = job.get("target")
        target = raw_target.strip() if isinstance(raw_target, str) else ""
        name = job.get("printer_name") or target or "this printer"

        # A printer whose address was never filled in, or has been cleared, arrives
        # here as JSON `null`. It is refused before the write rather than left to the
        # transport, because `str(None)` is the string `"None"` -- and for `usb` or
        # `bluetooth` that is a *relative file of that name*, which `send_device`
        # creates and writes the slip into quite successfully. The job would then be
        # recorded and acked, and the printers screen would show a slip that no paper
        # ever carried: the one failure a kitchen cannot detect, and the thing the
        # record-then-ack order in `store.py` exists to make impossible.
        #
        # Reported rather than dropped, so it lands against this printer on the admin
        # screen with the remedy in it. Nothing is recorded, so the job still prints
        # when the address is corrected and the server redelivers it.
        if not target:
            logger.error("job %s carries no printer address", job_id)
            await self._report(
                socket,
                "failed",
                job_id,
                error=f"{name} has no address configured - set its target "
                "under Printing > Print agents in the store dashboard",
            )
            return

        # A write for this very job that an earlier timeout gave up on and that has not
        # ended: wait on it again rather than starting another. Two writes of one job
        # against one printer is two slips, and `to_thread` cannot cancel the first.
        write = self._writes.get(job_id)
        if write is None:
            # In a thread because every transport blocks, and with a timeout (below)
            # because a printer can accept a connection and then never read a byte.
            write = asyncio.ensure_future(
                asyncio.to_thread(
                    transports.send,
                    connection,
                    target,
                    data,
                    timeout=self.config.print_timeout,
                )
            )
            self._writes[job_id] = write

        try:
            # Shielded, so the timeout abandons the wait and leaves the write running --
            # which is all `to_thread` allows in any case.
            async with asyncio.timeout(self.config.print_timeout):
                await asyncio.shield(write)
        except TimeoutError:
            logger.error("printer %s did not finish job %s in time", name, job_id)
            # The printer may still take the bytes. If it does, that is paper, and the
            # server's redelivery must be answered from the record, not printed again.
            write.add_done_callback(lambda finished: self._landed_late(job_id, name, finished))
            await self._report(socket, "failed", job_id, error=f"{name} did not respond in time")
            return
        except transports.TransportError as exc:
            self._writes.pop(job_id, None)
            logger.error("printer %s refused job %s: %s", name, job_id, exc)
            await self._report(socket, "failed", job_id, error=str(exc))
            return
        except Exception:
            # Something no transport is meant to raise. The write has ended, so its
            # failed result must not be kept: after the reconnect the server hands the
            # job back, and waiting on the old failure would crash the agent again each
            # time until it was restarted.
            self._writes.pop(job_id, None)
            raise
        self._writes.pop(job_id, None)

        # Paper is out. Record before acking: a crash now means the server redelivers
        # and the check above answers it, while the other order would mark a slip done
        # that never printed.
        if job_id not in self.printed:
            self.printed.record(job_id)
        logger.info("printed job %s on %s", job_id, name)
        await self._report(socket, "printed", job_id)

    def _landed_late(self, job_id: str, name: str, write: asyncio.Future[None]) -> None:
        """A write we had stopped waiting for has ended.

        Success means the slip came out after all, so it is recorded exactly as if it had
        been seen to: the job was reported failed and the server will hand it back, and
        the record is what turns that redelivery into an ack instead of a second slip. A
        failure is only logged -- nothing printed, and the redelivery will try again.
        """
        if self._writes.get(job_id) is write:
            del self._writes[job_id]
        if write.cancelled():
            return
        error = write.exception()  # also marks it retrieved
        if error is not None:
            logger.info("job %s: the abandoned write failed too: %s", job_id, error)
            return
        if job_id not in self.printed:
            self.printed.record(job_id)
            logger.info(
                "printed job %s on %s (the printer took it after the timeout)",
                job_id,
                name,
            )

    async def _report(self, socket: Any, kind: str, job_id: str, error: str | None = None) -> None:
        """Tell the server how a job ended.

        A closed socket is suppressed rather than raised. The job is recorded locally
        either way, the server hands unacked jobs back on disconnect, and the reconnect
        will ack it from the record -- so failing loudly here would only lose the
        remaining jobs in the queue.
        """
        frame: dict[str, Any] = {"type": kind, "job_id": job_id}
        if error is not None:
            frame["error"] = error[:500]
        with contextlib.suppress(websockets.ConnectionClosed):
            await socket.send(json.dumps(frame))


async def _next(
    queue: asyncio.Queue[dict[str, Any]], closing: asyncio.Event
) -> dict[str, Any] | None:
    """The next job, or `None` once we are shutting down.

    A plain `await queue.get()` cannot be interrupted, and the queue never gets another
    item after the socket closes -- so without this the printer task would outlive every
    connection. Racing the event is the whole trick.

    Losing a job that was put while we were cancelling the get is acceptable *here* and
    only here: we are shutting down, the socket is gone, so nothing queued could have
    been acked anyway. The server hands every unacked job back.
    """
    getter = asyncio.ensure_future(queue.get())
    stopping = asyncio.ensure_future(closing.wait())
    try:
        await asyncio.wait((getter, stopping), return_when=asyncio.FIRST_COMPLETED)
        if getter.done() and not getter.cancelled():
            return getter.result()
        return None
    finally:
        for task in (getter, stopping):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


def _parse(raw: str | bytes) -> dict[str, Any]:
    """One frame, as a dict, whatever arrived.

    Never raises. A frame we cannot read becomes an empty dict, which every caller
    already treats as an unknown type -- the alternative is an agent that stops
    printing because a single frame was malformed.
    """
    try:
        text = raw.decode() if isinstance(raw, bytes) else raw
        message = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("ignoring a frame that is not JSON")
        return {}
    return message if isinstance(message, dict) else {}
