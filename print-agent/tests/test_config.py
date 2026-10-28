"""Reading the two lines an admin has to get right.

Most of this file is about the URL, because it is the field most likely to be wrong and
the only one whose wrongness is invisible: a bad token is refused in a sentence, while a
URL missing its path produces a socket that connects to the web app and waits forever
for a `ready` frame nobody is going to send.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from print_agent import config

pytestmark = pytest.mark.unit


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "agent.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_two_required_fields_are_enough(tmp_path: Path):
    loaded = config.load(
        write(tmp_path, 'url = "https://mallt.example.com"\ntoken = "abc.def"\n'),
        environ={},
    )
    assert loaded.url == "wss://mallt.example.com/ws/print-agent"
    assert loaded.token == "abc.def"
    assert loaded.paper_width == config.DEFAULT_PAPER_WIDTH


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("https://x.example.com", "wss://x.example.com/ws/print-agent"),
        ("http://192.168.1.9:8000", "ws://192.168.1.9:8000/ws/print-agent"),
        ("wss://x.example.com", "wss://x.example.com/ws/print-agent"),
        ("ws://localhost:8000", "ws://localhost:8000/ws/print-agent"),
        ("https://x.example.com/", "wss://x.example.com/ws/print-agent"),
        (
            "https://x.example.com/ws/print-agent",
            "wss://x.example.com/ws/print-agent",
        ),
    ],
)
def test_whatever_the_admin_pastes_becomes_the_agent_endpoint(
    tmp_path: Path, given: str, expected: str
):
    """An admin pastes what is in their address bar, which is `https://`.

    Rewriting it is not leniency for its own sake: refusing would produce an error about
    a URL scheme, and the person reading it does not know that a WebSocket has a
    different one.
    """
    loaded = config.load(write(tmp_path, f'url = "{given}"\ntoken = "t"\n'), environ={})
    assert loaded.url == expected


def test_an_already_complete_url_is_not_given_the_path_twice(tmp_path: Path):
    loaded = config.load(
        write(tmp_path, 'url = "wss://x.example.com/ws/print-agent"\ntoken = "t"\n'),
        environ={},
    )
    assert loaded.url.count("/ws/print-agent") == 1


@pytest.mark.parametrize("given", ["mallt.example.com", "ftp://x", "  "])
def test_a_url_that_is_not_an_address_is_refused(tmp_path: Path, given: str):
    with pytest.raises(config.ConfigError):
        config.load(write(tmp_path, f'url = "{given}"\ntoken = "t"\n'), environ={})


def test_a_missing_token_says_where_to_get_one(tmp_path: Path):
    """The message is the feature.

    Whoever sees this has not paired the PC yet, and the useful thing to tell them is
    which screen does it -- not that a field is absent.
    """
    with pytest.raises(config.ConfigError, match="Printing > Print agents"):
        config.load(write(tmp_path, 'url = "https://x.example.com"\n'), environ={})


def test_a_missing_url_names_the_setting_and_the_variable(tmp_path: Path):
    with pytest.raises(config.ConfigError, match="MALLT_AGENT_URL"):
        config.load(write(tmp_path, 'token = "t"\n'), environ={})


def test_no_file_and_no_environment_is_refused_rather_than_defaulted():
    """An agent pointed at nothing sits in a reconnect loop against localhost.

    That failure looks exactly like a network problem, which is the hardest kind of
    misconfiguration to diagnose over the phone -- so it is refused at startup instead.
    """
    with pytest.raises(config.ConfigError):
        config.load(Path("does-not-exist.toml"), environ={})


def test_the_environment_can_supply_everything_with_no_file():
    """How the packaged binary is driven under a service manager."""
    loaded = config.load(
        Path("does-not-exist.toml"),
        environ={
            "MALLT_AGENT_URL": "https://x.example.com",
            "MALLT_AGENT_TOKEN": "env-token",
        },
    )
    assert loaded.token == "env-token"


def test_the_environment_wins_over_the_file(tmp_path: Path):
    loaded = config.load(
        write(tmp_path, 'url = "https://file.example.com"\ntoken = "file-token"\n'),
        environ={"MALLT_AGENT_TOKEN": "env-token"},
    )
    assert loaded.token == "env-token"
    assert "file.example.com" in loaded.url


def test_a_token_is_stripped_of_whitespace(tmp_path: Path):
    """Because it arrives via a copy button and a paste into a text editor."""
    loaded = config.load(
        write(tmp_path, 'url = "https://x.example.com"\ntoken = "  abc.def  "\n'),
        environ={},
    )
    assert loaded.token == "abc.def"


def test_broken_toml_is_reported_with_the_file_name(tmp_path: Path):
    path = write(tmp_path, 'url = "https://x.example.com\ntoken = "t"\n')
    with pytest.raises(config.ConfigError, match="agent.toml"):
        config.load(path, environ={})


@pytest.mark.parametrize("width", [0, 19, 97, 1000])
def test_an_unusable_paper_width_is_refused(tmp_path: Path, width: int):
    """Neither bound is arbitrary: below 20 no item name survives wrapping, and above
    96 is wider than any thermal paper sold, so it is a typo rather than a choice."""
    with pytest.raises(config.ConfigError):
        config.load(
            write(
                tmp_path,
                f'url = "https://x.example.com"\ntoken = "t"\npaper_width = {width}\n',
            ),
            environ={},
        )


@pytest.mark.parametrize("width", [32, 48])
def test_both_paper_sizes_are_accepted(tmp_path: Path, width: int):
    loaded = config.load(
        write(
            tmp_path,
            f'url = "https://x.example.com"\ntoken = "t"\npaper_width = {width}\n',
        ),
        environ={},
    )
    assert loaded.paper_width == width


def test_a_paper_width_from_the_environment_is_read_as_a_number(tmp_path: Path):
    """Environment variables are strings, and `40` from one is not `40` from TOML."""
    loaded = config.load(
        write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n'),
        environ={"MALLT_AGENT_PAPER_WIDTH": "48"},
    )
    assert loaded.paper_width == 48


def test_a_non_numeric_paper_width_is_refused(tmp_path: Path):
    with pytest.raises(config.ConfigError, match="paper_width"):
        config.load(
            write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n'),
            environ={"MALLT_AGENT_PAPER_WIDTH": "wide"},
        )


def test_a_zero_print_timeout_is_refused(tmp_path: Path):
    """It would report every job failed before the printer had read a byte."""
    with pytest.raises(config.ConfigError):
        config.load(
            write(
                tmp_path,
                'url = "https://x.example.com"\ntoken = "t"\nprint_timeout = 0\n',
            ),
            environ={},
        )


@pytest.mark.parametrize(
    ("given", "expected"),
    [("false", False), ("0", False), ("no", False), ("true", True), ("on", True)],
)
def test_tls_verification_can_be_turned_off_deliberately(
    tmp_path: Path, given: str, expected: bool
):
    """A hotel behind a self-signed proxy is a real deployment.

    It is a switch in a file rather than a fallback after a failed handshake: the
    difference is whether turning it off was somebody's decision.
    """
    loaded = config.load(
        write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n'),
        environ={"MALLT_AGENT_VERIFY_TLS": given},
    )
    assert loaded.verify_tls is expected


def test_verification_is_on_unless_it_was_turned_off(tmp_path: Path):
    loaded = config.load(
        write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n'), environ={}
    )
    assert loaded.verify_tls is True


def test_nonsense_in_the_tls_field_is_refused_rather_than_read_as_off(tmp_path: Path):
    """The dangerous default. A truthiness check would read "off-ish" values as on and
    some strings as off; either way the admin would not know which they got."""
    with pytest.raises(config.ConfigError, match="verify_tls"):
        config.load(
            write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n'),
            environ={"MALLT_AGENT_VERIFY_TLS": "maybe"},
        )


def test_the_printed_record_sits_beside_the_config_by_default(tmp_path: Path):
    """So a folder copied to a new PC carries its record with it.

    That is the outcome we want: the server may still be holding unacked jobs for that
    agent, and a fresh record would reprint every one of them.
    """
    path = write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n')
    loaded = config.load(path, environ={})
    assert loaded.printed_log.parent == path.parent
    assert loaded.printed_log.name == "printed-jobs.log"


def test_the_state_directory_can_be_moved(tmp_path: Path):
    loaded = config.load(
        write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n'),
        environ={"MALLT_AGENT_STATE_DIR": str(tmp_path / "state")},
    )
    assert loaded.printed_log == tmp_path / "state" / "printed-jobs.log"


def test_the_config_path_can_come_from_the_environment(tmp_path: Path):
    """For a service install that keeps its configuration somewhere else."""
    path = tmp_path / "elsewhere.toml"
    path.write_text('url = "https://x.example.com"\ntoken = "found"\n', encoding="utf-8")
    loaded = config.load(None, environ={"MALLT_AGENT_CONFIG": str(path)})
    assert loaded.token == "found"


def test_a_config_is_frozen_once_loaded(tmp_path: Path):
    """Nothing reassigns these, and a mutable config is a thing to check for later."""
    loaded = config.load(
        write(tmp_path, 'url = "https://x.example.com"\ntoken = "t"\n'), environ={}
    )
    with pytest.raises(AttributeError):
        loaded.token = "other"  # type: ignore[misc]


def _frozen_at(monkeypatch, exe: Path) -> None:
    """Make the process look like the PyInstaller binary at `exe`."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def test_a_packaged_agent_reads_the_config_beside_the_program_not_the_working_directory(
    tmp_path: Path, monkeypatch
):
    """Task Scheduler starts the program with `System32` as its working directory."""
    program = tmp_path / "install"
    program.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    write(program, 'url = "https://x.example.com"\ntoken = "from-program"\n')
    _frozen_at(monkeypatch, program / "print-agent.exe")
    monkeypatch.chdir(elsewhere)

    loaded = config.load(environ={})

    assert loaded.token == "from-program"
    assert loaded.state_dir.resolve() == program.resolve()


def test_a_source_run_still_reads_the_working_directory(tmp_path: Path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    write(tmp_path, 'url = "https://x.example.com"\ntoken = "from-cwd"\n')
    monkeypatch.chdir(tmp_path)

    loaded = config.load(environ={})

    assert loaded.token == "from-cwd"
    assert loaded.state_dir.resolve() == tmp_path.resolve()


def test_the_environment_override_beats_the_program_folder(tmp_path: Path, monkeypatch):
    program = tmp_path / "install"
    program.mkdir()
    write(program, 'url = "https://x.example.com"\ntoken = "from-program"\n')
    other = tmp_path / "other.toml"
    other.write_text('url = "https://x.example.com"\ntoken = "from-env"\n', encoding="utf-8")
    _frozen_at(monkeypatch, program / "print-agent.exe")

    loaded = config.load(environ={"MALLT_AGENT_CONFIG": str(other)})

    assert loaded.token == "from-env"


def test_an_explicit_path_beats_everything(tmp_path: Path, monkeypatch):
    program = tmp_path / "install"
    program.mkdir()
    write(program, 'url = "https://x.example.com"\ntoken = "from-program"\n')
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    chosen = write(explicit, 'url = "https://x.example.com"\ntoken = "explicit"\n')
    _frozen_at(monkeypatch, program / "print-agent.exe")

    assert config.load(chosen, environ={}).token == "explicit"
