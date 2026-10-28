from __future__ import annotations

import pytest

from print_agent import detect
from print_agent.detect import Detector, Found

pytestmark = pytest.mark.unit

LPSTAT_V = """\
device for Laser_Office: ipp://192.168.1.20/ipp/print
device for POS-80: usb://Printer/POS-80?serial=ABC
device for Kitchen Printer: socket://192.168.1.51:9100
garbage line
"""


def test_parse_lpstat_lists_queues_and_marks_the_default() -> None:
    found = detect.parse_lpstat(LPSTAT_V, "system default destination: POS-80\n")
    assert [f.name for f in found] == ["Laser_Office", "POS-80", "Kitchen Printer"]
    pos = found[1]
    assert (pos.connection, pos.target, pos.is_default, pos.driver) == (
        "system",
        "POS-80",
        True,
        "usb",
    )
    assert not found[0].is_default
    assert detect.parse_lpstat("", "no system default destination") == []


def test_device_files_classify_by_name() -> None:
    found = detect.device_files(
        ["/dev/usb/lp0", "/dev/rfcomm0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/null"]
    )
    kinds = {f.target: f.connection for f in found}
    assert kinds == {
        "/dev/usb/lp0": "usb",
        "/dev/rfcomm0": "bluetooth",
        "/dev/ttyUSB1": "usb",
        "/dev/ttyACM0": "usb",
    }


def test_com_ports_accept_only_com_names() -> None:
    found = detect.com_ports(["COM3", "com4", "LPT1", "COM3", "COM"])
    assert [f.target for f in found] == ["COM3", "com4"]
    assert all(f.connection == "bluetooth" for f in found)


def test_windows_queues_and_default() -> None:
    found = detect.windows_queues(
        [
            {"name": "POS58", "driver": "Generic / Text Only"},
            {"name": ""},
            {"name": "Office"},
        ],
        "POS58",
    )
    assert [(f.name, f.is_default, f.driver) for f in found] == [
        ("POS58", True, "Generic / Text Only"),
        ("Office", False, None),
    ]


def test_lan_candidates_cover_the_slash_24_without_self_loopback_or_link_local() -> None:
    hosts = detect.lan_candidates("192.168.1.7")
    assert len(hosts) == 253 and "192.168.1.7" not in hosts and "192.168.1.1" in hosts
    for bad in ("127.0.0.1", "169.254.3.4", "::1", "nonsense"):
        assert detect.lan_candidates(bad) == []


def test_linux_detection_combines_cups_and_devices() -> None:
    calls = []

    def run(cmd: list[str]) -> str:
        calls.append(cmd)
        return LPSTAT_V if cmd == ["lpstat", "-v"] else "system default destination: POS-80"

    d = Detector(
        platform="linux",
        run=run,
        list_devices=lambda pat: ["/dev/usb/lp0"] if pat == "/dev/usb/lp*" else [],
    )
    keys = {f.key for f in d.local()}
    assert keys == {
        "queue:Laser_Office",
        "queue:POS-80",
        "queue:Kitchen Printer",
        "dev:/dev/usb/lp0",
    }
    assert ["lpstat", "-v"] in calls


def test_windows_detection_uses_the_injected_os_calls() -> None:
    d = Detector(
        platform="win32",
        win_queues=lambda: ([{"name": "POS58", "driver": "x"}], "POS58"),
        win_ports=lambda: ["COM3"],
    )
    assert {f.key for f in d.local()} == {"queue:POS58", "com:COM3"}


def test_detection_never_raises() -> None:
    def boom() -> tuple[list, None]:
        raise RuntimeError("driver exploded")

    assert Detector(platform="win32", win_queues=boom).local() == []


def test_lan_scan_returns_only_hosts_that_answer_on_9100() -> None:
    d = Detector(
        local_ips=lambda: ["10.0.0.5", "10.0.0.5"],
        probe=lambda ip, port: ip in {"10.0.0.50", "10.0.0.77"} and port == 9100,
    )
    found = d.scan_lan()
    assert [f.target for f in found] == ["10.0.0.50:9100", "10.0.0.77:9100"]
    assert all(f.connection == "lan" and f.key.startswith("lan:") for f in found)
    assert Detector(local_ips=lambda: [], probe=lambda *_: True).scan_lan() == []


def test_found_serialises_for_the_wire() -> None:
    f = Found("queue:A", "A", "system", "A", None, True)
    assert f.as_dict() == {
        "key": "queue:A",
        "name": "A",
        "connection": "system",
        "target": "A",
        "driver": None,
        "is_default": True,
    }
