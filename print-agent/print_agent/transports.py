"""Getting bytes to the hardware, three ways.

`needs.md` KOT rule 2 asks for USB, LAN and Bluetooth, and the server tells us which
in every job frame -- `connection` and `target` travel with the job precisely so this
app holds no printer configuration of its own (`print_queue.job_frame`). So this module
is a dispatch on one enum value and nothing more clever.

**Every function here blocks.** They are called through `asyncio.to_thread` by the
client, because a printer that is out of paper can stall a write for as long as it
likes, and the socket still has to answer heartbeats while that happens. The blocking
form is kept plain rather than made async: there is no async file IO for a device node
on Windows, and a half-async transport layer would hide which half could stall.

**A timeout abandons the wait, not the thread.** Python cannot cancel a blocked
`write()` to a device. The client therefore prints one job at a time, so an abandoned
write cannot interleave with the next one -- and a job whose write is still stuck when
we give up is reported failed, which is the truthful answer: we do not know whether
paper came out, and `needs.md` would rather a store reprint than believe a slip exists.
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
from typing import Final

#: The de facto raw-printing port (JetDirect/RAW). Every LAN thermal printer we have
#: seen listens here, so a target may omit it.
DEFAULT_LAN_PORT: Final = 9100

#: Bluetooth RFCOMM channel 1. Serial-port-profile printers use it; there is no
#: discovery step worth doing for a device an admin has already paired by hand.
RFCOMM_CHANNEL: Final = 1


class TransportError(Exception):
    """The bytes did not reach the printer.

    One exception type for all three transports: the client's only decision is
    printed-or-failed, and a caller that branched on transport-specific errors would
    be deciding something it has no better information about than the message.
    """


def _split_host_port(target: str) -> tuple[str, int]:
    """`host`, `host:port`, or a bracketed IPv6 form.

    IPv6 is handled not because a store will use it, but because the unbracketed
    `rsplit(":")` that ignores it would silently read `fe80::1` as host `fe80:` on
    port... nothing that parses, and fail with a confusing message instead of a clear
    one.
    """
    value = target.strip()
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if rest.startswith(":"):
            return host, _port(rest[1:], value)
        return host, DEFAULT_LAN_PORT

    host, sep, port = value.rpartition(":")
    if not sep:
        return value, DEFAULT_LAN_PORT
    if host.count(":") >= 1:
        # Bare IPv6 with no port: every colon belongs to the address.
        return value, DEFAULT_LAN_PORT
    return host, _port(port, value)


def _port(raw: str, target: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        raise TransportError(f"target {target!r} has a non-numeric port") from None
    if not 1 <= port <= 65535:
        raise TransportError(f"target {target!r} has a port out of range")
    return port


def send_lan(target: str, data: bytes, *, timeout: float) -> None:
    """A TCP connection per job, closed after.

    Not a pooled connection. A thermal printer accepts one session at a time and holds
    a dead one open for minutes after a cable is pulled; reconnecting per job means the
    failure surfaces on the job it belongs to rather than on some later one.

    `shutdown(SHUT_WR)` before closing: several printers discard a partially received
    buffer when the socket closes without the write side being finished first, which
    shows up as a slip missing its last lines.
    """
    host, port = _split_host_port(target)
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall(data)
            # A printer that has already gone is nothing to report here: the bytes were
            # accepted, and this call only tells it there are no more coming.
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_WR)
    except TimeoutError as exc:
        raise TransportError(f"{host}:{port} did not answer in {timeout:g}s") from exc
    except OSError as exc:
        raise TransportError(f"{host}:{port} refused the job: {exc}") from exc


def send_device(target: str, data: bytes) -> None:
    """A write to a device path or printer share.

    Covers `/dev/usb/lp0` on Linux, `\\\\localhost\\POS58` for a shared Windows queue
    and `COM3` for a Bluetooth serial port, because on all three the operating system
    has already made the printer a thing you write bytes to. Writing the file is the
    whole driver.

    Opened unbuffered *and* flushed explicitly. The flush is what guarantees delivery --
    with it, a buffered handle would behave identically -- so `buffering=0` is belt and
    braces for the case the flush cannot cover: an exception between the write and the
    flush, where a buffered handle discards bytes the printer never saw while an
    unbuffered one has already passed them to the OS.
    """
    try:
        # The string as given, not `Path(target).open`: pathlib rewrites a Windows share
        # `\\localhost\POS58` to `\\localhost\POS58\`, and Windows refuses that spelling
        # with "Invalid argument".
        with open(target, "wb", buffering=0) as device:
            device.write(data)
            device.flush()
    except OSError as exc:
        raise TransportError(f"{target} would not accept the job: {exc}") from exc


def send_bluetooth(target: str, data: bytes, *, timeout: float) -> None:
    """RFCOMM to a paired MAC, or a serial port that stands in for one.

    Windows exposes a paired printer as a COM port and has no RFCOMM sockets in
    CPython, so a target that is not a MAC is handed to `send_device`. That is not a
    fallback for an error case: on Windows it is the only form that exists, which is
    why it is chosen by the shape of the target rather than after a failure.
    """
    if not _looks_like_mac(target):
        send_device(target, data)
        return

    family = getattr(socket, "AF_BLUETOOTH", None)
    protocol = getattr(socket, "BTPROTO_RFCOMM", None)
    if family is None or protocol is None:
        raise TransportError(
            f"{target} is a bluetooth address, but this machine has no RFCOMM support "
            "- pair the printer and give its serial port instead"
        )

    try:
        with socket.socket(family, socket.SOCK_STREAM, protocol) as connection:
            connection.settimeout(timeout)
            connection.connect((target.upper(), RFCOMM_CHANNEL))
            connection.sendall(data)
    except TimeoutError as exc:
        raise TransportError(f"{target} did not answer in {timeout:g}s") from exc
    except OSError as exc:
        raise TransportError(f"{target} refused the job: {exc}") from exc


def send_system(target: str, data: bytes, *, timeout: float) -> None:
    """Raw bytes to an operating-system print queue, bypassing the driver's rendering.

    Windows: the spooler with datatype RAW (via ctypes, no dependency). Elsewhere: CUPS
    `lp -o raw`. The queue name is passed as an argument, never through a shell."""
    if sys.platform == "win32":
        _send_spooler(target, data)
        return
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["lp", "-d", target, "-o", "raw"],  # noqa: S607
            input=data,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TransportError(f"{target} did not accept the job in {timeout:g}s") from exc
    except OSError as exc:
        raise TransportError(f"could not run lp for {target}: {exc}") from exc
    if done.returncode != 0:
        detail = done.stderr.decode(errors="replace").strip()[:200]
        raise TransportError(f"{target} refused the job: {detail or done.returncode}")


def _send_spooler(target: str, data: bytes) -> None:  # pragma: no cover - needs Windows
    import ctypes
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)  # type: ignore[attr-defined]

    class DOC_INFO_1W(ctypes.Structure):
        _fields_ = [  # noqa: RUF012
            ("pDocName", wintypes.LPWSTR),
            ("pOutputFile", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR),
        ]

    handle = wintypes.HANDLE()
    if not winspool.OpenPrinterW(target, ctypes.byref(handle), None):
        raise TransportError(f"could not open printer {target!r} (is the name right?)")
    try:
        doc = DOC_INFO_1W("MallT", None, "RAW")
        if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise TransportError(f"{target} would not start a job")
        try:
            winspool.StartPagePrinter(handle)
            written = wintypes.DWORD(0)
            ok = winspool.WritePrinter(handle, data, len(data), ctypes.byref(written))
            winspool.EndPagePrinter(handle)
            if not ok or written.value != len(data):
                raise TransportError(f"{target} accepted only part of the job")
        finally:
            winspool.EndDocPrinter(handle)
    finally:
        winspool.ClosePrinter(handle)


def _looks_like_mac(target: str) -> bool:
    parts = target.strip().replace("-", ":").split(":")
    if len(parts) != 6:
        return False
    return all(len(part) == 2 and _is_hex(part) for part in parts)


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def send(connection: str, target: str, data: bytes, *, timeout: float) -> None:
    """One job's bytes, by whichever route the server named.

    An unrecognised `connection` is a `TransportError` like any other, so it is
    reported against the job and shows up on the printers screen next to the printer
    that has it -- rather than raising through the socket loop, where an admin would
    see an agent that keeps reconnecting and no reason why.
    """
    if connection == "lan":
        send_lan(target, data, timeout=timeout)
    elif connection == "usb":
        send_device(target, data)
    elif connection == "bluetooth":
        send_bluetooth(target, data, timeout=timeout)
    elif connection == "system":
        send_system(target, data, timeout=timeout)
    else:
        raise TransportError(f"unknown connection kind {connection!r}")
