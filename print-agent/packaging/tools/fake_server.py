"""A stand-in for the MallT server's /ws/print-agent socket, for testing installers.

Accepts the tokens given with --token (repeatable). A probe handshake is answered
`ready` and then left to close; a normal one is answered `ready` and held open with
heartbeats. Any other token is closed with the policy code, which is what the real
server does for every kind of refusal.

    python fake_server.py --port 8765 --token good
"""

from __future__ import annotations

import argparse
import asyncio
import json

from websockets.asyncio.server import serve

CLOSE_POLICY = 1008


async def handle(connection, tokens: set[str]) -> None:
    try:
        first = json.loads(await connection.recv())
    except Exception:
        await connection.close(code=CLOSE_POLICY)
        return
    if not isinstance(first, dict) or first.get("token") not in tokens:
        await connection.close(code=CLOSE_POLICY)
        return

    await connection.send(json.dumps({"v": 1, "type": "ready", "agent_id": "fake-agent"}))
    if first.get("probe") is True:
        return  # the handler returning closes the socket
    while True:
        await asyncio.sleep(3)
        await connection.send(json.dumps({"v": 1, "type": "heartbeat"}))


async def main(port: int, tokens: set[str]) -> None:
    async def handler(connection) -> None:
        await handle(connection, tokens)

    async with serve(handler, "127.0.0.1", port) as server:
        bound = server.sockets[0].getsockname()[1]
        print(f"listening on ws://127.0.0.1:{bound}", flush=True)
        await asyncio.get_running_loop().create_future()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", action="append", default=[])
    args = parser.parse_args()
    asyncio.run(main(args.port, set(args.token) or {"good"}))
