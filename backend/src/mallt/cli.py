"""Operational commands: ``python -m mallt.cli openapi | seed-admin``."""

import argparse
import asyncio
import getpass
import json
import os
import sys
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from mallt.core.config import Settings, get_settings
from mallt.core.db import make_engine
from mallt.core.errors import AppError, Conflict
from mallt.main import create_app
from mallt.modules.iam.seed import seed_admin


def build_openapi() -> dict[str, Any]:
    """The OpenAPI schema, built without a running server or database connection."""
    app = create_app(Settings(env="test"))
    schema: dict[str, Any] = app.openapi()
    return schema


async def run_seed_admin(
    settings: Settings, username: str, display_name: str, password: str
) -> str:
    engine = make_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            uri = await seed_admin(
                session, username=username, display_name=display_name, password=password
            )
            await session.commit()
            return uri
    finally:
        await engine.dispose()


def _read_password() -> str:
    if password := os.environ.get("MALLT_ADMIN_PASSWORD"):
        return password
    first = getpass.getpass("Password (min 10 characters): ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    return first


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m mallt.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("openapi", help="print the OpenAPI schema as JSON")
    seed = sub.add_parser("seed-admin", help="create the first Platform Admin")
    seed.add_argument("--username", required=True)
    seed.add_argument("--display-name", required=True)
    args = parser.parse_args(argv)

    if args.command == "openapi":
        json.dump(build_openapi(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    try:
        uri = asyncio.run(
            run_seed_admin(get_settings(), args.username, args.display_name, _read_password())
        )
    except Conflict:
        sys.stderr.write(f"User '{args.username}' already exists.\n")
        return 1
    except AppError as exc:
        sys.stderr.write(f"{exc.code}: {exc.detail or exc.title}\n")
        return 1
    sys.stdout.write(
        "Platform admin created. Add this to an authenticator app now; it is shown only once:\n"
        f"{uri}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
