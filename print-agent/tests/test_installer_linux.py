"""install.sh / uninstall.sh, run for real against a fake server.

Run with `--skip-service`, so the suite needs neither root nor systemd: it exercises
the installer's own logic (validation, backup, config merge, `--check`, rollback) with
the real built binary (`dist/linux-<arch>/pyi/print-agent`, from `build.sh`). The
systemd side is verified by hand in the last task. Paths contain a space on purpose.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ARCH = "arm64" if platform.machine() in ("aarch64", "arm64") else "x64"
BINARY = ROOT / "dist" / f"linux-{ARCH}" / "pyi" / "print-agent"
LINUX = ROOT / "packaging" / "linux"
FAKE_SERVER = ROOT / "packaging" / "tools" / "fake_server.py"

pytestmark = [
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux installer"),
    pytest.mark.skipif(not BINARY.exists(), reason="run build.sh first"),
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server():
    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(FAKE_SERVER),
            "--port",
            str(port),
            "--token",
            "good",
            "--token",
            "good2",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().startswith("listening")
    yield f"http://127.0.0.1:{port}"
    proc.kill()
    proc.wait()


@pytest.fixture
def release(tmp_path: Path) -> Path:
    folder = tmp_path / "unzipped release"
    folder.mkdir()
    shutil.copy2(BINARY, folder / "print-agent")
    for item in LINUX.iterdir():
        shutil.copy2(item, folder / item.name)
    shutil.copy2(ROOT / "agent.example.toml", folder / "agent.example.toml")
    return folder


@pytest.fixture
def dirs(tmp_path: Path) -> dict[str, Path]:
    base = tmp_path / "Ravi Kumar"
    return {
        "install": base / "opt",
        "config": base / "etc",
        "state": base / "var",
        "unit": base / "units",
    }


def flags(dirs: dict[str, Path]) -> list[str]:
    return [
        "--install-dir",
        str(dirs["install"]),
        "--config-dir",
        str(dirs["config"]),
        "--state-dir",
        str(dirs["state"]),
        "--unit-dir",
        str(dirs["unit"]),
        "--skip-service",
    ]


def install(release: Path, dirs, url: str, token: str):
    return subprocess.run(
        ["bash", str(release / "install.sh"), "--url", url, "--token", token, *flags(dirs)],
        capture_output=True,
        text=True,
        timeout=120,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_fresh_install_copies_the_program_and_writes_the_config(release, dirs, server):
    result = install(release, dirs, server, "good")

    assert result.returncode == 0, result.stderr + result.stdout
    assert (dirs["install"] / "print-agent").exists()
    config = (dirs["config"] / "agent.toml").read_text()
    assert f'url = "{server}"' in config
    assert 'token = "good"' in config
    assert oct((dirs["config"] / "agent.toml").stat().st_mode & 0o777) == "0o640"


def test_the_token_is_never_echoed(release, dirs, server):
    result = install(release, dirs, server, "good")
    assert result.returncode == 0
    assert "good" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("url", "token"),
    [
        ("http://127.0.0.1:1", 'a"b'),
        ("http://127.0.0.1:1", "a b"),
        ("http://127.0.0.1:1", "a;touch /tmp/pwned"),
        ("http://127.0.0.1:1", "PASTE-THE-PAIRING-TOKEN-HERE"),
        ('http://127.0.0.1:1/"; touch /tmp/pwned "', "good"),
        ("ftp://127.0.0.1:1", "good"),
        ("https://mallt.example.com", "good"),
    ],
)
def test_a_hostile_or_placeholder_value_is_refused_before_anything_is_written(
    release, dirs, url, token
):
    result = install(release, dirs, url, token)

    assert result.returncode != 0
    assert "Install stopped" in result.stdout + result.stderr
    assert not dirs["install"].exists()
    assert not dirs["config"].exists()
    assert not Path("/tmp/pwned").exists()


def test_re_running_the_install_keeps_other_settings_and_the_printed_record(release, dirs, server):
    assert install(release, dirs, server, "good").returncode == 0
    config = dirs["config"] / "agent.toml"
    config.write_text(config.read_text() + "paper_width = 48\n")
    record = dirs["state"] / "printed-jobs.log"
    record.write_text("11111111-1111-1111-1111-111111111111\n")

    result = install(release, dirs, server, "good2")

    assert result.returncode == 0, result.stderr + result.stdout
    text = config.read_text()
    assert 'token = "good2"' in text
    assert "paper_width = 48" in text
    assert text.count("url =") == 1
    assert text.count("token =") == 1
    assert record.read_text().startswith("11111111")


def test_a_refused_token_leaves_an_existing_install_untouched(release, dirs, server):
    assert install(release, dirs, server, "good").returncode == 0
    binary_before = digest(dirs["install"] / "print-agent")
    config_before = (dirs["config"] / "agent.toml").read_text()

    result = install(release, dirs, server, "revoked")

    assert result.returncode != 0
    assert "refused" in (result.stdout + result.stderr).lower()
    assert digest(dirs["install"] / "print-agent") == binary_before
    assert (dirs["config"] / "agent.toml").read_text() == config_before


def test_an_unreachable_server_changes_nothing_on_a_reinstall(release, dirs, server):
    assert install(release, dirs, server, "good").returncode == 0
    config_before = (dirs["config"] / "agent.toml").read_text()

    result = install(release, dirs, "http://127.0.0.1:1", "good")

    assert result.returncode != 0
    assert "could not reach" in (result.stdout + result.stderr).lower()
    assert (dirs["config"] / "agent.toml").read_text() == config_before


def test_an_unreachable_server_leaves_no_half_install_on_a_fresh_machine(release, dirs):
    result = install(release, dirs, "http://127.0.0.1:1", "good")

    assert result.returncode != 0
    assert not (dirs["install"] / "print-agent").exists()
    assert not (dirs["config"] / "agent.toml").exists()


def test_the_installer_refuses_to_run_without_the_program_beside_it(release, dirs, server):
    (release / "print-agent").unlink()

    result = install(release, dirs, server, "good")

    assert result.returncode != 0
    assert "unzipped folder" in result.stdout + result.stderr


def test_uninstall_keeps_settings_and_the_printed_record_unless_purged(release, dirs, server):
    assert install(release, dirs, server, "good").returncode == 0
    (dirs["state"] / "printed-jobs.log").write_text("x\n")

    kept = subprocess.run(
        ["bash", str(release / "uninstall.sh"), *flags(dirs)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert kept.returncode == 0, kept.stderr
    assert not (dirs["install"] / "print-agent").exists()
    assert (dirs["config"] / "agent.toml").exists()
    assert (dirs["state"] / "printed-jobs.log").exists()

    purged = subprocess.run(
        ["bash", str(release / "uninstall.sh"), "--purge", *flags(dirs)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert purged.returncode == 0, purged.stderr
    assert not dirs["config"].exists()
    assert not dirs["state"].exists()


def test_every_shell_script_is_valid_bash_and_has_lf_endings():
    for script in LINUX.glob("*.sh"):
        assert b"\r" not in script.read_bytes(), f"{script.name} has CRLF endings"
        subprocess.run(["bash", "-n", str(script)], check=True)
    assert b"\r" not in (LINUX / "mallt-print-agent.service").read_bytes()
