"""Pairing credentials for the print agent: ``<agent_id>.<secret>``, secret hashed with argon2."""

import logging
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.security import hash_password, verify_password
from mallt.modules.printing.models import PrintAgent
from mallt.modules.printing.repository import PrintingRepository

log = logging.getLogger(__name__)
_SECRET_BYTES = 32
_PREFIX_LEN = 8


def issue(agent_id: uuid.UUID) -> tuple[str, str, str]:
    """(wire token, hash to store, prefix kept for display)."""
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    return f"{agent_id}.{secret}", hash_password(secret), secret[:_PREFIX_LEN]


def split_token(token: str) -> tuple[uuid.UUID, str] | None:
    agent_id, _, secret = token.partition(".")
    if not secret:
        return None
    try:
        return uuid.UUID(agent_id), secret
    except ValueError:
        return None


async def authenticate(session: AsyncSession, token: str) -> PrintAgent | None:
    """The active agent this token belongs to, or None. One answer for every kind of failure."""
    parts = split_token(token)
    if parts is None:
        return None
    agent_id, secret = parts
    agent = await PrintingRepository(session).agent(agent_id)
    if agent is None or not agent.is_active:
        return None
    return agent if verify_password(agent.token_hash, secret) else None


async def mark_seen(session: AsyncSession, agent: PrintAgent, version: str | None = None) -> None:
    agent.last_seen_at = datetime.now(UTC)
    if version:
        agent.version = version[:20]
    await session.flush()
