"""Getting bytes to hardware that is not here.

There is no printer in CI, so what these tests can actually check is the part that goes
wrong without one: the address parsing, the dispatch on connection kind, and that every
failure arrives as `TransportError` rather than as an `OSError` nobody catches.

The LAN tests use a real socket on loopback. A mock would assert that we called
`sendall`, which is not the thing that breaks -- what breaks is a target string parsed
into the wrong port, and only a real connection can catch that.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from print_agent import transports

pytestmark = pytest.mark.unit


class Listener:
    """A one-shot TCP server standing in for a LAN printer.

    Accepts one connection, reads to EOF, and keeps what it got. Reading to EOF is what
    makes this a useful fake: it only terminates because `send_lan` shuts the write side
    down, so a regression that stopped doing that would hang this test rather than
    passing it.
    """

    def __init__(self) -> None:
        self._server = socket.create_server(("127.0.0.1", 0))
        self._server.settimeout(5)
        self.received = b""
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def target(self) -> str:
        host, port = self._server.getsockname()[:2]
        return f"{host}:{port}"

    def _serve(self) -> None:
        try:
            connection, _ = self._server.accept()
        except OSError:
            return
        with connection:
            while chunk := connection.recv(4096):
                self.received += chunk

    def close(self) -> None:
        self._thread.join(timeout=5)
        self._server.close()


@pytest.fixture
def listener():
    server = Listener()
    yield server
    server.close()


# --- Target parsing ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("192.168.1.50", ("192.168.1.50", transports.DEFAULT_LAN_PORT)),
        ("192.168.1.50:9100", ("192.168.1.50", 9100)),
        ("192.168.1.50:515", ("192.168.1.50", 515)),
        ("printer.local", ("printer.local", transports.DEFAULT_LAN_PORT)),
        ("  192.168.1.50  ", ("192.168.1.50", transports.DEFAULT_LAN_PORT)),
        ("[fe80::1]:9100", ("fe80::1", 9100)),
        ("[fe80::1]", ("fe80::1", transports.DEFAULT_LAN_PORT)),
        ("fe80::1", ("fe80::1", transports.DEFAULT_LAN_PORT)),
    ],
)
def test_a_target_is_read_as_host_and_port(target: str, expected: tuple[str, int]):
    """An admin types a bare IP, because that is what the printer's label shows.

    The IPv6 forms are here not because a hotel will use one, but because the naive
    `rsplit(":")` that ignores them reads `fe80::1` as a host of `fe80:` and fails with
    a message about a port -- which is a confusing error rather than a working default.
    """
    assert transports._split_host_port(target) == expected


@pytest.mark.parametrize("target", ["192.168.1.50:printer", "192.168.1.50:0"])
def test_an_unusable_port_is_a_transport_error(target: str):
    """Not a `ValueError` escaping into the socket loop.

    Every failure here has to arrive as one type, because the client's only decision is
    printed-or-failed and the message is what ends up next to the printer on the admin
    screen.
    """
    with pytest.raises(transports.TransportError):
        transports._split_host_port(target)


# --- LAN -----------------------------------------------------------------------------


def test_lan_delivers_every_byte(listener: Listener):
    transports.send_lan(listener.target, b"\x1b@hello\n", timeout=5)
    listener.close()
    assert listener.received == b"\x1b@hello\n"


def test_lan_delivers_a_payload_too_large_for_one_write(listener: Listener):
    """`sendall`, not `send`: a partial write would truncate the slip.

    This does *not* also prove the write side was shut down, though an earlier version
    of this test claimed it did. Closing a socket sends FIN too, so the listener reaches
    EOF either way and cannot tell the two apart -- which is why that behaviour has a
    test of its own below.
    """
    payload = bytes(range(32)) * 200
    transports.send_lan(listener.target, payload, timeout=5)
    listener.close()
    assert listener.received == payload


def test_lan_finishes_the_write_side_before_closing(listener: Listener):
    """Several printers discard a partly-received buffer when a socket closes without the
    write side being shut down first, which shows up as a slip missing its last lines --
    including the cut, so the paper cannot be torn off.

    Asserted by watching for the call rather than by what arrives, because no listener
    can observe the difference: a close delivers EOF exactly as a shutdown does. That
    makes this the one place a spy is the honest instrument rather than a shortcut.
    """
    shutdowns: list[int] = []
    real = socket.socket.shutdown

    def record(self, how):
        shutdowns.append(how)
        return real(self, how)

    socket.socket.shutdown = record
    try:
        transports.send_lan(listener.target, b"\x1b@x\n", timeout=5)
    finally:
        socket.socket.shutdown = real
    listener.close()

    assert socket.SHUT_WR in shutdowns


def test_a_printer_that_is_not_there_is_reported_not_raised():
    """A closed port on loopback, which is the fastest reliable refusal available.

    Either wording is accepted because which one you get is the platform's choice: a
    closed loopback port answers with a refusal on Linux and, on this Windows machine,
    times out instead. Both are the same fact about the printer, and both have to arrive
    as `TransportError`.
    """
    with socket.create_server(("127.0.0.1", 0)) as probe:
        port = probe.getsockname()[1]

    with pytest.raises(transports.TransportError, match="refused|did not answer"):
        transports.send_lan(f"127.0.0.1:{port}", b"x", timeout=0.5)


def test_an_address_that_does_not_resolve_is_reported_not_raised():
    """A hostname nothing can look up, which is the *non-timeout* socket failure.

    Worth its own case because the timeout above cannot cover this branch: on this
    platform a closed port times out, so without a name that fails to resolve the
    `except OSError` arm is never exercised and an `OSError` escaping into the socket
    loop would go unnoticed. `gaierror` is an `OSError`, so this is that arm.

    It is also the realistic version of the mistake -- an admin typing a printer's
    hostname with a typo in it.
    """
    with pytest.raises(transports.TransportError, match="refused the job"):
        transports.send_lan("printer.invalid.:9100", b"x", timeout=2)


def test_the_error_names_the_address_that_failed():
    """So an admin reading it knows which printer to go and look at."""
    with socket.create_server(("127.0.0.1", 0)) as probe:
        port = probe.getsockname()[1]

    with pytest.raises(transports.TransportError, match=f"127.0.0.1:{port}"):
        transports.send_lan(f"127.0.0.1:{port}", b"x", timeout=0.5)


# --- Device paths --------------------------------------------------------------------


def test_a_device_write_delivers_every_byte(tmp_path: Path):
    """`/dev/usb/lp0`, `\\\\localhost\\POS58` and `COM3` are all a file to write to.

    A regular file stands in for all three: the operating system has already made the
    printer something you write bytes to, and writing the file is the whole driver.
    """
    device = tmp_path / "lp0"
    transports.send_device(str(device), b"\x1b@ticket\n")
    assert device.read_bytes() == b"\x1b@ticket\n"


def test_a_device_write_is_flushed_before_it_returns(tmp_path: Path):
    """Unbuffered, so the cut command cannot be left in Python's buffer while the job
    looks finished -- and the next thing an admin does is unplug the printer."""
    device = tmp_path / "lp0"
    transports.send_device(str(device), b"a" * 100_000)
    assert device.stat().st_size == 100_000


def test_a_device_target_is_opened_exactly_as_typed(monkeypatch: pytest.MonkeyPatch):
    """A Windows share is opened by the string the admin typed, never through `Path`.

    `Path(r"\\\\localhost\\RP80")` renders as `\\\\localhost\\RP80\\` -- a trailing backslash
    that Windows rejects with "Invalid argument" -- so the shared-queue address
    this module's own docstring names could never print. The tests above cannot see
    it: a plain file path survives a `Path` round trip on every OS.
    """
    opened: list[str] = []

    class Sink:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, data: bytes) -> int:
            return len(data)

        def flush(self) -> None:
            pass

    def fake_open(file, mode="r", buffering=-1):
        opened.append(file)
        return Sink()

    monkeypatch.setattr(transports, "open", fake_open, raising=False)

    transports.send_device(r"\\localhost\RP80", b"x")

    assert opened == [r"\\localhost\RP80"]


def test_a_missing_device_is_reported_with_its_path(tmp_path: Path):
    """The path is the diagnosis: `/dev/usb/lp1` when the printer is on `lp0` is the
    single most common way a printer is configured wrong."""
    missing = tmp_path / "nope" / "lp0"
    with pytest.raises(transports.TransportError, match="lp0"):
        transports.send_device(str(missing), b"x")


# --- Bluetooth -----------------------------------------------------------------------


@pytest.mark.parametrize("target", ["00:11:22:33:44:55", "00-11-22-33-44-55", "aa:bb:cc:dd:ee:ff"])
def test_a_mac_address_is_recognised_in_either_notation(target: str):
    assert transports._looks_like_mac(target)


@pytest.mark.parametrize(
    "target", ["COM3", "/dev/rfcomm0", "00:11:22:33:44", "zz:11:22:33:44:55", ""]
)
def test_what_is_not_a_mac_is_not_treated_as_one(target: str):
    assert not transports._looks_like_mac(target)


def test_a_paired_printer_given_as_a_serial_port_is_written_to(tmp_path: Path):
    """On Windows this is the only form that exists.

    CPython has no RFCOMM sockets there, so a paired printer appears as a COM port --
    which is why the choice is made by the shape of the target rather than after an
    RFCOMM attempt has failed.
    """
    device = tmp_path / "COM3"
    transports.send_bluetooth(str(device), b"\x1b@bt\n", timeout=5)
    assert device.read_bytes() == b"\x1b@bt\n"


def test_a_mac_on_a_machine_without_rfcomm_says_what_to_do_instead(monkeypatch):
    """Windows, in other words -- where this is a configuration problem, not a bug.

    The message has to name the remedy, because "no RFCOMM support" alone would send an
    admin looking for a missing driver rather than pairing the printer and reading its
    COM port.
    """
    monkeypatch.delattr(socket, "AF_BLUETOOTH", raising=False)
    with pytest.raises(transports.TransportError, match="serial port"):
        transports.send_bluetooth("00:11:22:33:44:55", b"x", timeout=1)


# --- Dispatch ------------------------------------------------------------------------


def test_usb_dispatches_to_a_device_write(tmp_path: Path):
    device = tmp_path / "lp0"
    transports.send("usb", str(device), b"usb", timeout=5)
    assert device.read_bytes() == b"usb"


def test_lan_dispatches_to_a_socket(listener: Listener):
    transports.send("lan", listener.target, b"lan", timeout=5)
    listener.close()
    assert listener.received == b"lan"


def test_bluetooth_dispatches_by_the_shape_of_its_target(tmp_path: Path):
    device = tmp_path / "COM4"
    transports.send("bluetooth", str(device), b"bt", timeout=5)
    assert device.read_bytes() == b"bt"


@pytest.mark.parametrize("connection", ["", "parallel", "USB", "serial"])
def test_a_connection_kind_we_do_not_know_is_reported_against_the_job(connection: str):
    """Including `USB` in capitals: the server sends the enum's lowercase value, so a
    capitalised one means something upstream changed and the job should surface as
    failed on the admin screen rather than raise through the socket loop -- where an
    admin would see an agent reconnecting and no reason why.
    """
    with pytest.raises(transports.TransportError, match="unknown connection"):
        transports.send(connection, "anything", b"x", timeout=1)
