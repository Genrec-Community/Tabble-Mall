"""Refresh-token sessions for both staff and customers.

A login creates a *family* of tokens. Each refresh rotates the token within the family. Replaying
an already-rotated token means it leaked, so the whole family is revoked. The access token's
``sid`` is the family id, which lets revoking a session end its access tokens immediately.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.config import Settings
from mallt.core.db import defer_after_commit
from mallt.core.enums import IdentityKind
from mallt.core.errors import Unauthorized
from mallt.core.ids import uuid7
from mallt.core.kv import KV
from mallt.core.security import hash_opaque, new_opaque_token
from mallt.modules.iam.models import RefreshToken
from mallt.modules.iam.repository import SessionRepository

ACTIVE_CACHE_TTL_S = 30


class RefreshReuse(Unauthorized):
    # The family revocation must survive even though this request ends in an error.
    commit_on_error = True

    def __init__(self) -> None:
        super().__init__("refresh_reuse", "Session reuse detected. Please sign in again.")


class SuspendedOnRefresh(Unauthorized):
    commit_on_error = True  # keep the family revocation made just before this is raised

    def __init__(self) -> None:
        super().__init__("account_suspended", "This account is suspended.")


@dataclass(frozen=True)
class SessionInfo:
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    user_agent: str | None
    ip: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _active_key(family_id: uuid.UUID) -> str:
    return f"sess:{family_id}"


class SessionService:
    def __init__(self, session: AsyncSession, settings: Settings, kv: KV) -> None:
        self.session = session
        self.repo = SessionRepository(session)
        self.settings = settings
        self.kv = kv

    def _ttl(self, kind: IdentityKind) -> timedelta:
        seconds = (
            self.settings.staff_refresh_ttl_s
            if kind == IdentityKind.STAFF
            else self.settings.customer_refresh_ttl_s
        )
        return timedelta(seconds=seconds)

    async def issue(
        self,
        kind: IdentityKind,
        subject_id: uuid.UUID,
        *,
        family_id: uuid.UUID | None = None,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[str, RefreshToken]:
        raw, token_hash = new_opaque_token()
        row = RefreshToken(
            identity_type=kind,
            subject_id=subject_id,
            family_id=family_id or uuid7(),
            token_hash=token_hash,
            expires_at=_now() + self._ttl(kind),
            user_agent=(user_agent or "")[:255] or None,
            ip=ip,
        )
        self.repo.add(row)
        return raw, row

    async def rotate(
        self,
        kind: IdentityKind,
        raw: str,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[str, RefreshToken]:
        row = await self.repo.by_hash(hash_opaque(raw))
        now = _now()
        if (
            row is None
            or row.identity_type != kind
            or row.revoked_at is not None
            or row.expires_at <= now
        ):
            raise Unauthorized("invalid_refresh", "Invalid or expired session.")
        if row.rotated_at is not None:
            await self.revoke_family(row.family_id)
            raise RefreshReuse
        row.rotated_at = now
        return await self.issue(
            kind, row.subject_id, family_id=row.family_id, user_agent=user_agent, ip=ip
        )

    async def family_of(self, raw: str) -> uuid.UUID | None:
        row = await self.repo.by_hash(hash_opaque(raw))
        return row.family_id if row else None

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        await self.repo.revoke_family(family_id, _now())
        key = _active_key(family_id)
        await self.kv.delete(key)
        # Again after the commit: a racing request may re-cache "still active" before it lands.
        defer_after_commit(self.session, partial(self.kv.delete, key))

    async def revoke_all(
        self,
        kind: IdentityKind,
        subject_id: uuid.UUID,
        *,
        except_family: uuid.UUID | None = None,
    ) -> None:
        for family_id in await self.repo.live_families(kind, subject_id, _now()):
            if family_id != except_family:
                await self.revoke_family(family_id)

    async def is_active(self, family_id: uuid.UUID) -> bool:
        if self.kv.fast and await self.kv.get(_active_key(family_id)):
            return True
        active = await self.repo.family_is_active(family_id, _now())
        if active and self.kv.fast:
            await self.kv.set(_active_key(family_id), "1", ACTIVE_CACHE_TTL_S)
        return active

    async def list_active(self, kind: IdentityKind, subject_id: uuid.UUID) -> list[SessionInfo]:
        families: dict[uuid.UUID, list[RefreshToken]] = {}
        for token in await self.repo.live_tokens(kind, subject_id, _now()):
            families.setdefault(token.family_id, []).append(token)
        return [
            SessionInfo(
                id=family_id,
                created_at=tokens[0].created_at,
                last_seen_at=tokens[-1].created_at,
                user_agent=tokens[0].user_agent,
                ip=tokens[0].ip,
            )
            for family_id, tokens in families.items()
        ]
