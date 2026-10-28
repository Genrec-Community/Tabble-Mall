"""The agent tells the server which printers it can see, and scans the network on request."""

from __future__ import annotations

import subprocess

import pytest

from print_agent import client, detect, transports
from print_agent.client import Agent
from tests.test_client import FakeServer, agent, config, printer, ready  # noqa: F401

pytestmark = pytest.mark.ws


class PrintersServer(FakeServer):
    """Holds the socket open until it has seen ``expect`` printer reports."""

    def reports(self) -> list[dict]:
        return [f for f in self.sent if f.get("type") == "printers"]


def local_printer() -> detect.Found:
    return detect.Found("queue:POS80", "POS80", "system", "POS80", "Generic", True)


def fake_detector(
    local: list[detect.Found], lan: list[detect.Found] | None = None
) -> detect.Detector:
    return detect.Detector(
        platform="linux",
        run=lambda cmd: "",
        list_devices=lambda pat: [],
        win_queues=lambda: ([], None),
        probe=lambda ip, port: False,
        local_ips=lambda: [],
    )


async def test_printers_are_reported_once_connected(agent: Agent) -> None:
    agent._detector = type(
        "D",
        (),
        {
            "local": lambda self: [local_printer()],  # type: ignore[attr-defined]
            "scan_lan": lambda self: [],
        },
    )()
    server = PrintersServer([ready()], expect=1)
    await agent.serve(server)
    (report,) = server.reports()
    assert report["scope"] == "local"
    assert report["items"] == [local_printer().as_dict()]


async def test_an_unchanged_list_is_not_sent_again(
    agent: Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(client, "REPORT_INTERVAL_SECONDS", 0.02)
    calls = {"n": 0}

    class D:
        def local(self) -> list[detect.Found]:
            calls["n"] += 1
            return (
                [local_printer()]
                if calls["n"] < 4
                else [
                    local_printer(),
                    detect.Found("com:COM3", "COM3", "bluetooth", "COM3"),
                ]
            )

        def scan_lan(self) -> list[detect.Found]:
            return []

    agent._detector = D()  # type: ignore[assignment]
    server = PrintersServer([ready()], expect=2)
    await agent.serve(server)
    first, second = server.reports()
    assert len(first["items"]) == 1 and len(second["items"]) == 2
    assert calls["n"] >= 4  # polled repeatedly, but only the change was sent


async def test_a_scan_request_runs_the_lan_scan_and_reports_it_as_lan(
    agent: Agent,
) -> None:
    found = detect.Found("lan:10.0.0.9", "Network printer 10.0.0.9", "lan", "10.0.0.9:9100")

    class D:
        def local(self) -> list[detect.Found]:
            return []

        def scan_lan(self) -> list[detect.Found]:
            return [found]

    agent._detector = D()  # type: ignore[assignment]
    server = PrintersServer([ready(), {"type": "scan_lan"}], expect=2)
    await agent.serve(server)
    scopes = {r["scope"]: r["items"] for r in server.reports()}
    assert scopes["lan"] == [found.as_dict()]
    assert scopes["local"] == []


async def test_a_system_queue_job_goes_to_the_system_transport(
    agent: Agent,
    printer,
    monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    job = {
        "job_id": "11111111-1111-1111-1111-111111111111",
        "printer_name": "POS80",
        "connection": "system",
        "target": "POS80",
        "kind": "test",
        "payload": {"kind": "test", "store": "S", "printer_name": "POS80"},
    }
    server = FakeServer([ready(), {"v": 1, "type": "job", "job": job}])
    await agent.serve(server)
    assert printer.jobs[0][:2] == ("system", "POS80")
    assert server.acked(job["job_id"])


# ---- the system transport itself (CUPS path; the Windows spooler path needs Windows) ----


def test_system_transport_pipes_raw_bytes_to_lp(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        seen.update(cmd=cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(transports.sys, "platform", "linux")
    monkeypatch.setattr(transports.subprocess, "run", fake_run)
    transports.send("system", "POS 80", b"\x1b@hello", timeout=5)
    assert seen["cmd"] == [
        "lp",
        "-d",
        "POS 80",
        "-o",
        "raw",
    ]  # one argv item: no shell, no splitting
    assert seen["input"] == b"\x1b@hello"


def test_system_transport_reports_failures_as_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transports.sys, "platform", "linux")

    def refuse(cmd, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(cmd, 1, b"", b"lp: The printer or class does not exist.")

    monkeypatch.setattr(transports.subprocess, "run", refuse)
    with pytest.raises(transports.TransportError, match="does not exist"):
        transports.send("system", "Ghost", b"x", timeout=5)

    def hang(cmd, **kwargs):  # noqa: ANN001, ANN003
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(transports.subprocess, "run", hang)
    with pytest.raises(transports.TransportError, match="did not accept"):
        transports.send("system", "Ghost", b"x", timeout=5)

    def missing(cmd, **kwargs):  # noqa: ANN001, ANN003
        raise FileNotFoundError("lp")

    monkeypatch.setattr(transports.subprocess, "run", missing)
    with pytest.raises(transports.TransportError, match="could not run lp"):
        transports.send("system", "Ghost", b"x", timeout=5)
