"""What this agent needs to know, and where it reads it from.

A **file** is the primary form, not environment variables. This app is installed on a
store PC by someone following a one-page instruction sheet, and "paste the token into
`agent.toml`" is a thing they can do twice a year without help; setting a persistent
environment variable on Windows is not. Environment variables still override, because
that is how the packaged binary gets driven under a service manager.

**The token is the only secret here and it is write-once from the admin's side.** The
server stores an argon2 hash and cannot return it (see the admin UI), so the copy in
this file is the only one. That is also why nothing in this module logs the config back
out: a config dump in a support log would put the credential somewhere it can be read.

No printer configuration lives here. The server sends `connection` and `target` with
every job, deliberately, so that a printer's address has exactly one home -- the
`printers` table an admin can see and edit.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

#: 58mm paper at Font A is 32 columns; 80mm is 48. 32 is the default because it is the
#: narrower of the two: a 48-column slip on 58mm paper wraps into unreadable mush,
#: while a 32-column slip on 80mm paper merely leaves a margin.
DEFAULT_PAPER_WIDTH: Final = 32

#: The widest and narrowest line anything may ask for. One definition, used for the
#: config file and for the width a job arrives with, so the two cannot disagree.
MIN_PAPER_WIDTH: Final = 20
MAX_PAPER_WIDTH: Final = 96

#: Reconnect backoff. Starts fast because the common disconnect is a flaky store
#: uplink that is back in a second, and caps low because an agent that is down is a
#: kitchen receiving nothing -- there is no load to protect the server from here, this
#: is one socket per store PC.
MIN_BACKOFF_SECONDS: Final = 1.0
MAX_BACKOFF_SECONDS: Final = 30.0

#: How long to wait on a printer before giving up on one job. Generous: a printer
#: waking from sleep can take several seconds before it accepts bytes, and a job
#: abandoned early is a slip a cook never sees.
DEFAULT_PRINT_TIMEOUT_SECONDS: Final = 20.0


class ConfigError(Exception):
    """The agent cannot start with what it was given.

    Raised rather than defaulted for the two fields that have no sensible default --
    the server URL and the token. An agent that started up pointed at nothing would
    sit in a reconnect loop against localhost, which looks identical to a network
    problem and is the hardest kind of misconfiguration to diagnose remotely.
    """


@dataclass(frozen=True, slots=True)
class Config:
    """Everything the client needs, resolved and validated."""

    url: str
    token: str
    paper_width: int = DEFAULT_PAPER_WIDTH
    print_timeout: float = DEFAULT_PRINT_TIMEOUT_SECONDS
    state_dir: Path = Path(".")
    verify_tls: bool = True
    #: Reserved for the signed self-update feature (not built yet).
    auto_update: bool = True
    #: The file this config was read from, handed to the new program's `--check`.
    config_path: Path | None = None

    @property
    def printed_log(self) -> Path:
        """Where the record of what has already come out lives.

        Under `state_dir` rather than beside the config, because the config is
        something an admin edits and this is something they must not: deleting it
        silently re-arms every job the server may still resend.
        """
        return self.state_dir / "printed-jobs.log"


def _coerce_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{field} must be a whole number, got {value!r}") from None


def _coerce_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{field} must be a number, got {value!r}") from None


def _coerce_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{field} must be true or false, got {value!r}")


def _websocket_url(raw: str) -> str:
    """The server's address, as a WebSocket URL ending at the agent endpoint.

    An admin will paste whatever they have in the address bar, so `https://` is
    accepted and rewritten -- a wrong scheme is not a mistake worth refusing to start
    over, and the alternative is an agent that fails with a message about a scheme the
    person did not know they had to change.
    """
    url = raw.strip().rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url[len("https://") :]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://") :]
    if not url.startswith(("ws://", "wss://")):
        raise ConfigError(f"server url {raw!r} should start with https:// or wss://")
    if not url.endswith("/ws/print-agent"):
        url = f"{url}/ws/print-agent"
    return url


def load(path: Path | None = None, environ: dict[str, str] | None = None) -> Config:
    """Read the config file, then let the environment override it.

    Both are optional individually -- a deployment driven entirely by environment
    variables needs no file, and a store PC needs no environment -- but between them
    the url and the token must be present.
    """
    environ = os.environ if environ is None else environ
    raw: dict[str, Any] = {}

    file_path = path or _configured_path(environ)
    if file_path is not None and file_path.exists():
        try:
            with file_path.open("rb") as handle:
                raw = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{file_path} is not valid TOML: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"{file_path} could not be read: {exc}") from exc

    for key, env_name in (
        ("url", "MALLT_AGENT_URL"),
        ("token", "MALLT_AGENT_TOKEN"),
        ("paper_width", "MALLT_AGENT_PAPER_WIDTH"),
        ("print_timeout", "MALLT_AGENT_PRINT_TIMEOUT"),
        ("state_dir", "MALLT_AGENT_STATE_DIR"),
        ("verify_tls", "MALLT_AGENT_VERIFY_TLS"),
        ("auto_update", "MALLT_AGENT_AUTO_UPDATE"),
    ):
        if environ.get(env_name):
            raw[key] = environ[env_name]

    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ConfigError(
            "no server url configured - set `url` in the config file or "
            "MALLT_AGENT_URL in the environment"
        )

    token = raw.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ConfigError(
            "no pairing token configured - pair this PC under Printing > Print agents in the "
            "store dashboard and paste the credential it shows into `token`"
        )

    width = (
        _coerce_int(raw["paper_width"], "paper_width")
        if "paper_width" in raw
        else DEFAULT_PAPER_WIDTH
    )
    if not MIN_PAPER_WIDTH <= width <= MAX_PAPER_WIDTH:
        raise ConfigError(
            f"paper_width {width} is outside {MIN_PAPER_WIDTH}-{MAX_PAPER_WIDTH} characters"
        )

    timeout = (
        _coerce_float(raw["print_timeout"], "print_timeout")
        if "print_timeout" in raw
        else DEFAULT_PRINT_TIMEOUT_SECONDS
    )
    if timeout <= 0:
        raise ConfigError("print_timeout must be greater than zero")

    if raw.get("state_dir"):
        state_dir = Path(str(raw["state_dir"]))
    else:
        state_dir = _default_state_dir(file_path)

    return Config(
        url=_websocket_url(url),
        token=token.strip(),
        paper_width=width,
        print_timeout=timeout,
        state_dir=state_dir,
        verify_tls=(_coerce_bool(raw["verify_tls"], "verify_tls") if "verify_tls" in raw else True),
        auto_update=(
            _coerce_bool(raw["auto_update"], "auto_update") if "auto_update" in raw else True
        ),
        config_path=file_path if file_path is not None and file_path.exists() else None,
    )


def _program_dir() -> Path:
    """The folder the program lives in, when it is the packaged binary.

    A PyInstaller binary sets `sys.frozen` and `sys.executable` names the real file
    (not the temporary folder a one-file build unpacks into). Run from source, the
    working directory is the right answer: that is where a developer put `agent.toml`.
    Task Scheduler and systemd both start a program somewhere unrelated, so for the
    packaged binary "beside the program" has to mean the program, not the cwd.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _configured_path(environ: dict[str, str]) -> Path | None:
    """Where to look for the file when the caller did not say.

    Beside the executable, which for a PyInstaller binary is the folder the admin
    unzipped -- the one place they can find again. `MALLT_AGENT_CONFIG` overrides for
    a service install that keeps config elsewhere.
    """
    if environ.get("MALLT_AGENT_CONFIG"):
        return Path(environ["MALLT_AGENT_CONFIG"])
    return _program_dir() / "agent.toml"


def _default_state_dir(config_path: Path | None) -> Path:
    """Beside the config file, so the two travel together.

    An agent moved to a new PC by copying its folder keeps its printed-jobs record,
    which is the outcome we want: the server may still be holding unacked jobs for it.
    """
    if config_path is not None:
        return config_path.parent
    return _program_dir()
