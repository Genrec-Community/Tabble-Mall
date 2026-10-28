"""Verifying Google Sign-In ID tokens."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

import urllib3
from google.auth.transport import urllib3 as google_urllib3
from google.oauth2 import id_token

from mallt.core.config import Settings
from mallt.core.errors import AppError, Unauthorized


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str | None
    name: str | None


class GoogleVerifier(Protocol):
    async def verify(self, id_token: str) -> GoogleIdentity: ...


class GoogleIdTokenVerifier:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self._http = urllib3.PoolManager()

    async def verify(self, token: str) -> GoogleIdentity:
        if not self.client_id:
            raise AppError("google_not_configured", "Google sign-in is off.", status=503)
        try:
            # Blocking (it may fetch Google's certificates), so keep it off the event loop.
            info = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                token,
                google_urllib3.Request(self._http),  # type: ignore[no-untyped-call]
                self.client_id,
            )
        except ValueError as exc:
            raise Unauthorized("invalid_google_token", "Google sign-in failed.") from exc
        verified = bool(info.get("email_verified"))
        return GoogleIdentity(
            sub=str(info["sub"]),
            email=info.get("email") if verified else None,
            name=info.get("name"),
        )


def make_google_verifier(settings: Settings) -> GoogleVerifier:
    return GoogleIdTokenVerifier(settings.google_client_id)
