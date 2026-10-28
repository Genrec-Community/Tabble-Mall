"""`python -m print_agent`, and the entry point the packaged binary runs.

Deliberately thin: read the config, start the client, and translate the two
unrecoverable outcomes into a message an admin can act on plus an exit code a service
manager can see. Everything else is `client.py`'s business.

**There is no test-print command.** It is the obvious thing to add for an installer
verifying the hardware, and it would need the connection kind and the device address
passed on the command line -- which would make this app the second place a printer's
address lives, when the whole reason the server sends `connection` and `target` with
every job is that there should only be one. A printer that is wired up wrong shows its
failure against its own row on the admin printers screen, which is where someone can
also fix it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import websockets

from .client import Agent, Rejected, check_credential
from .config import Config, ConfigError, load
from .lock import AlreadyRunning, InstanceLock

#: Exit codes. Distinguished because a service manager should restart an agent that
#: lost its network and should *not* restart one that can never succeed: a revoked
#: credential, an unusable config, or a second copy that would only fight the first.
#: Restarting any of those is an endless loop with nobody ever told. `EXIT_UNREACHABLE`
#: is only ever the answer to `--check`; a running agent just keeps retrying.
EXIT_CONFIG: int = 2
EXIT_REJECTED: int = 3
EXIT_LOCKED: int = 4
EXIT_UNREACHABLE: int = 5


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="print-agent",
        description=(
            "Prints kitchen slips and bills for one store. Pair this PC under "
            "Printing > Print agents in the store dashboard to get a token."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="config file to read (default: agent.toml beside the program)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log every frame, for working out why a slip did not come out",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "dial the server once, confirm the credential is accepted, and exit "
            "(0 accepted, 3 refused, 5 server unreachable); touches no printer and "
            "no job"
        ),
    )
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    """Logs to stderr, with timestamps.

    Timestamps because the only question ever asked of these logs is "did anything
    happen when the 7pm order went in", and stderr because a service manager captures
    it while a log file of our own would be a third path an admin has to find.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # The library logs every ping and pong at DEBUG, which buries our own frames in a
    # verbose run -- and a verbose run is only ever asked for to read our frames.
    logging.getLogger("websockets").setLevel(logging.INFO)


def _check(config: Config) -> int:
    """`--check`: is the credential accepted? The installer's last gate.

    Says nothing about the token. The config's own address is shown because "could not
    reach <address>" is what lets an admin spot a typo.
    """
    try:
        asyncio.run(check_credential(config))
    except Rejected as exc:
        print(f"print-agent check: the credential was refused - {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except (OSError, TimeoutError, websockets.WebSocketException) as exc:
        print(f"print-agent check: could not reach {config.url} - {exc}", file=sys.stderr)
        return EXIT_UNREACHABLE
    print("print-agent check: the server accepted the credential")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    try:
        config = load(args.config)
    except ConfigError as exc:
        # To stderr as well as the log, and without a traceback: the reader is an admin
        # who mistyped a line in a TOML file, and a stack trace would bury the sentence
        # that tells them which line.
        print(f"print-agent cannot start: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.check:
        return _check(config)

    lock = InstanceLock(config.state_dir)
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        print(f"print-agent cannot start: {exc}", file=sys.stderr)
        return EXIT_LOCKED
    except OSError as exc:
        print(
            f"print-agent cannot start: the state folder {config.state_dir} is not usable - {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        asyncio.run(Agent(config).run_forever())
    except Rejected as exc:
        print(f"print-agent was refused: {exc}", file=sys.stderr)
        return EXIT_REJECTED
    except KeyboardInterrupt:
        # Ctrl-C on a store PC is how this is normally stopped. Not an error, and not
        # worth a traceback.
        logging.getLogger(__name__).info("stopped")
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
