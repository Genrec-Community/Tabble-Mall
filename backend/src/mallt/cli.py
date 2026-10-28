"""Operational commands: ``python -m mallt.cli openapi | seed-admin``."""

import json
import sys
from typing import Any

from mallt.core.config import Settings
from mallt.main import create_app


def build_openapi() -> dict[str, Any]:
    """The OpenAPI schema, built without a running server or database connection."""
    app = create_app(Settings(env="test"))
    schema: dict[str, Any] = app.openapi()
    return schema


def main(argv: list[str]) -> int:
    if len(argv) == 1 and argv[0] == "openapi":
        json.dump(build_openapi(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    sys.stderr.write("usage: python -m mallt.cli openapi\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
