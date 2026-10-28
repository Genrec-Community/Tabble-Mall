"""Live order updates over a WebSocket (store dashboard and customer order page).

The first frame is ``{"token": <access token>, "channel": "store", "store_id": ...}`` or
``{"token": ..., "channel": "customer"}``. The token is checked exactly like an HTTP request
(live session, active account, permissions). After that the server only pushes small events;
clients re-fetch details over the normal authorised API.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Protocol

from fastapi import FastAPI

from mallt.core.errors import AppError
from mallt.core.rbac import P, Scope
from mallt.core.security import decode_access_token
from mallt.modules.iam.authz import AuthzService
from mallt.modules.iam.deps import customer_id_for, staff_principal_for
from mallt.modules.tenancy.service import TenancyService

log = logging.getLogger(__name__)
CLOSE_POLICY = 1008
AUTH_TIMEOUT_S = 10.0
HEARTBEAT_S = 25.0


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def receive_text(self) -> str: ...
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


class Refused(Exception):
    pass


async def _channel(ws: WebSocketLike, app: FastAPI) -> str:
    """Authenticate the first frame and return the bus channel the socket may listen to."""
    try:
        async with asyncio.timeout(AUTH_TIMEOUT_S):
            raw = await ws.receive_text()
        parsed: Any = json.loads(raw) if len(raw) < 4096 else None
        if not isinstance(parsed, dict):
            raise Refused
        frame: dict[str, Any] = parsed
        token = frame.get("token")
        if not isinstance(token, str):
            raise Refused
        claims = decode_access_token(app.state.settings, token)
        async with app.state.session_factory() as session:
            if claims.typ == "customer" and frame.get("channel") == "customer":
                cid = await customer_id_for(claims, session, app.state.settings, app.state.kv)
                return f"customer:{cid}"
            if claims.typ == "staff" and frame.get("channel") == "store":
                store_id = uuid.UUID(str(frame.get("store_id")))
                principal = await staff_principal_for(
                    claims, session, app.state.settings, app.state.kv
                )
                store = await TenancyService(session, app.state.kv).get_store(principal, store_id)
                scope = Scope.store(store.organization_id, store.mall_id, store.id)
                AuthzService(session, app.state.kv).require(principal, P.STORE_ORDER_READ, scope)
                return f"store:{store.id}"
    except (TimeoutError, ValueError, AppError, json.JSONDecodeError, AttributeError) as exc:
        raise Refused from exc
    raise Refused


async def serve_orders(ws: WebSocketLike, app: FastAPI) -> None:
    await ws.accept()
    try:
        channel = await _channel(ws, app)
    except Refused:
        await ws.close(code=CLOSE_POLICY)  # one answer for every kind of refusal
        return
    bus = app.state.bus
    async with bus.subscribe(channel) as messages:
        await ws.send_text(json.dumps({"type": "ready"}))
        incoming: asyncio.Task[Any] = asyncio.ensure_future(anext(messages))
        client: asyncio.Task[str] = asyncio.ensure_future(ws.receive_text())
        # A socket is only as trustworthy as the token it was opened with, so it lives no longer
        # than an access token: logout, suspension and removed roles take effect by then, and the
        # browser reconnects with a fresh token.
        deadline = asyncio.get_running_loop().time() + app.state.settings.access_ttl_s
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    await ws.close(code=1000)
                    return
                done, _ = await asyncio.wait(
                    {incoming, client},
                    timeout=min(HEARTBEAT_S, remaining),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    await ws.send_text(json.dumps({"type": "ping"}))
                    continue
                if incoming in done:
                    await ws.send_text(json.dumps(incoming.result()))
                    incoming = asyncio.ensure_future(anext(messages))
                if client in done:
                    client.result()  # raises when the browser went away; pings are ignored
                    client = asyncio.ensure_future(ws.receive_text())
        except Exception:  # noqa: BLE001 - a vanished client is ordinary
            log.debug("order socket ended", exc_info=True)
        finally:
            for task in (incoming, client):
                task.cancel()
