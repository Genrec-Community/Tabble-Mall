"""Finding the printers attached to this PC, so the owner can pick from a list.

Everything that touches the operating system is an injectable function, so the parsing and
the decisions are tested on any machine; only the thin OS calls at the bottom are not.

* **Windows** - installed print queues (`EnumPrintersW` via ctypes, no dependency) and COM
  ports from the registry. A queue is printed to *raw* through the spooler, which is how
  almost every Windows thermal printer is installed.
* **Linux** - CUPS queues (`lpstat`), `/dev/usb/lp*`, serial and rfcomm devices.
* **Network** - an on-demand sweep of the local /24 for TCP 9100 (RAW/JetDirect). Only run
  when the dashboard asks, never on a schedule: scanning a network is not something to do
  unprompted on a customer's router.

Detection only *lists*. Nothing is printed, opened or configured here, and a printer that is
listed but wrong is corrected in the dashboard.
"""

from __future__ import annotations

import glob
import ipaddress
import logging
import re
import socket
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

LAN_PORT = 9100
SCAN_TIMEOUT = 0.3
SCAN_WORKERS = 64
MAX_PRINTERS = 100


@dataclass(frozen=True)
class Found:
    key: str
    name: str
    connection: str  # usb | lan | bluetooth | system
    target: str
    driver: str | None = None
    is_default: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------- parsing (pure)

_LPSTAT_DEVICE = re.compile(r"^device for (?P<name>.+?): (?P<uri>\S+)\s*$")


def parse_lpstat(devices: str, default_output: str = "") -> list[Found]:
    """`lpstat -v` (and `lpstat -d` for the default) -> CUPS queues, printed raw by name."""
    default = ""
    m = re.search(r"destination: (\S+)", default_output)
    if m:
        default = m.group(1)
    out: list[Found] = []
    for raw in devices.splitlines():
        m = _LPSTAT_DEVICE.match(raw.strip())
        if not m:
            continue
        name = m.group("name")
        out.append(
            Found(
                key=f"queue:{name}",
                name=name,
                connection="system",
                target=name,
                driver=m.group("uri").split("://")[0],
                is_default=name == default,
            )
        )
    return out


def device_files(paths: list[str]) -> list[Found]:
    """Device nodes that are writable printer-ish endpoints."""
    out: list[Found] = []
    for path in sorted(paths):
        base = path.rsplit("/", 1)[-1]
        if base.startswith("rfcomm"):
            out.append(Found(f"dev:{path}", f"Bluetooth printer ({base})", "bluetooth", path))
        elif base.startswith("lp"):
            out.append(Found(f"dev:{path}", f"USB printer ({base})", "usb", path))
        elif base.startswith(("ttyUSB", "ttyACM")):
            out.append(Found(f"dev:{path}", f"Serial printer ({base})", "usb", path))
    return out


def com_ports(names: list[str]) -> list[Found]:
    return [
        Found(f"com:{n}", f"Serial / Bluetooth port {n}", "bluetooth", n)
        for n in sorted(set(names))
        if re.fullmatch(r"COM\d+", n, flags=re.IGNORECASE)
    ]


def windows_queues(rows: list[dict[str, object]], default: str | None) -> list[Found]:
    out: list[Found] = []
    for row in rows:
        name = str(row.get("name") or "")
        if not name:
            continue
        driver = row.get("driver")
        out.append(
            Found(
                key=f"queue:{name}",
                name=name,
                connection="system",
                target=name,
                driver=str(driver) if driver else None,
                is_default=name == default,
            )
        )
    return out


def lan_candidates(local_ip: str) -> list[str]:
    """Every other host on the /24 around ``local_ip``."""
    try:
        addr = ipaddress.ip_address(local_ip)
    except ValueError:
        return []
    if not isinstance(addr, ipaddress.IPv4Address) or addr.is_loopback or addr.is_link_local:
        return []
    net = ipaddress.ip_network(f"{addr}/24", strict=False)
    return [str(h) for h in net.hosts() if h != addr]


# ---------------------------------------------------------------- the detector


def _run(cmd: list[str]) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


def _probe(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=SCAN_TIMEOUT):
            return True
    except OSError:
        return False


def _local_ips() -> list[str]:
    """This PC's IPv4 addresses (the route to an outside address, without sending anything)."""
    ips: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: nothing is sent
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(str(info[4][0]))
    except OSError:
        pass
    return sorted(ips)


class Detector:
    def __init__(
        self,
        *,
        platform: str = sys.platform,
        run: Callable[[list[str]], str] = _run,
        list_devices: Callable[[str], list[str]] = glob.glob,
        win_queues: Callable[[], tuple[list[dict[str, object]], str | None]] | None = None,
        win_ports: Callable[[], list[str]] | None = None,
        probe: Callable[[str, int], bool] = _probe,
        local_ips: Callable[[], list[str]] = _local_ips,
    ) -> None:
        self.platform = platform
        self._run = run
        self._glob = list_devices
        self._win_queues = win_queues or _windows_enum_printers
        self._win_ports = win_ports or _windows_serial_ports
        self._probe = probe
        self._local_ips = local_ips

    def local(self) -> list[Found]:
        """OS print queues and device ports; fast, safe to run every minute."""
        found: list[Found] = []
        try:
            if self.platform == "win32":
                rows, default = self._win_queues()
                found += windows_queues(rows, default)
                found += com_ports(self._win_ports())
            else:
                found += parse_lpstat(self._run(["lpstat", "-v"]), self._run(["lpstat", "-d"]))
                paths = [
                    p
                    for pat in (
                        "/dev/usb/lp*",
                        "/dev/ttyUSB*",
                        "/dev/ttyACM*",
                        "/dev/rfcomm*",
                    )
                    for p in self._glob(pat)
                ]
                found += device_files(paths)
        except Exception:  # noqa: BLE001 - detection must never take the agent down
            logger.exception("printer detection failed")
        unique = {f.key: f for f in found}
        return list(unique.values())[:MAX_PRINTERS]

    def scan_lan(self) -> list[Found]:
        """Sweep the local /24 for printers listening on port 9100."""
        hosts: list[str] = []
        for ip in self._local_ips():
            hosts += [h for h in lan_candidates(ip) if h not in hosts]
        if not hosts:
            return []
        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
            results = list(pool.map(lambda h: (h, self._probe(h, LAN_PORT)), hosts))
        return [
            Found(f"lan:{h}", f"Network printer {h}", "lan", f"{h}:{LAN_PORT}")
            for h, ok in results
            if ok
        ][:MAX_PRINTERS]


# ---------------------------------------------------------------- Windows (ctypes; no dependency)


def _windows_enum_printers() -> tuple[list[dict[str, object]], str | None]:  # pragma: no cover
    import ctypes
    from ctypes import wintypes

    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)  # type: ignore[attr-defined]

    class PRINTER_INFO_2W(ctypes.Structure):
        _fields_ = [  # noqa: RUF012
            ("pServerName", wintypes.LPWSTR),
            ("pPrinterName", wintypes.LPWSTR),
            ("pShareName", wintypes.LPWSTR),
            ("pPortName", wintypes.LPWSTR),
            ("pDriverName", wintypes.LPWSTR),
            ("pComment", wintypes.LPWSTR),
            ("pLocation", wintypes.LPWSTR),
            ("pDevMode", ctypes.c_void_p),
            ("pSepFile", wintypes.LPWSTR),
            ("pPrintProcessor", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR),
            ("pParameters", wintypes.LPWSTR),
            ("pSecurityDescriptor", ctypes.c_void_p),
            ("Attributes", wintypes.DWORD),
            ("Priority", wintypes.DWORD),
            ("DefaultPriority", wintypes.DWORD),
            ("StartTime", wintypes.DWORD),
            ("UntilTime", wintypes.DWORD),
            ("Status", wintypes.DWORD),
            ("cJobs", wintypes.DWORD),
            ("AveragePages", wintypes.DWORD),
        ]

    flags = 0x2 | 0x4  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed, returned = wintypes.DWORD(0), wintypes.DWORD(0)
    winspool.EnumPrintersW(flags, None, 2, None, 0, ctypes.byref(needed), ctypes.byref(returned))
    if needed.value == 0:
        return [], None
    buffer = ctypes.create_string_buffer(needed.value)
    if not winspool.EnumPrintersW(
        flags, None, 2, buffer, needed, ctypes.byref(needed), ctypes.byref(returned)
    ):
        return [], None
    infos = ctypes.cast(buffer, ctypes.POINTER(PRINTER_INFO_2W))
    rows = [
        {
            "name": infos[i].pPrinterName,
            "driver": infos[i].pDriverName,
            "port": infos[i].pPortName,
        }
        for i in range(returned.value)
    ]
    size = wintypes.DWORD(0)
    winspool.GetDefaultPrinterW(None, ctypes.byref(size))
    default: str | None = None
    if size.value:
        name = ctypes.create_unicode_buffer(size.value)
        if winspool.GetDefaultPrinterW(name, ctypes.byref(size)):
            default = name.value
    return rows, default


def _windows_serial_ports() -> list[str]:  # pragma: no cover
    import winreg  # type: ignore[import-not-found]

    names: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            index = 0
            while True:
                try:
                    _, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                names.append(str(value))
                index += 1
    except OSError:
        pass
    return names
