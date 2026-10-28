import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Depends, Request
from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mallt.core.errors import AppError
from mallt.core.ids import uuid7

log = logging.getLogger(__name__)

AfterCommit = Callable[[], Awaitable[None]]

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def normalize_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Make a libpq-style URL (e.g. from Neon) usable by SQLAlchemy+asyncpg.

    Returns the asyncpg URL and the connect_args it needs: asyncpg takes ``ssl`` rather than
    ``sslmode``, and pgbouncer-style poolers (Neon ``-pooler`` hosts) need prepared statements off.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    args: dict[str, Any] = {}
    kept = []
    for key, value in parse_qsl(parts.query):
        if key == "sslmode":
            if value != "disable":
                args["ssl"] = True
        elif key != "channel_binding":
            kept.append((key, value))
    if "-pooler" in (parts.hostname or ""):
        args["statement_cache_size"] = 0
    new = parts._replace(scheme=scheme, query=urlencode(kept))
    return urlunsplit(new), args


def make_engine(url: str) -> AsyncEngine:
    normalized, connect_args = normalize_database_url(url)
    return create_async_engine(
        normalized,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        connect_args=connect_args,
    )


def defer_after_commit(session: AsyncSession, callback: AfterCommit) -> None:
    """Run ``callback`` once this request's transaction has committed (never if it rolls back).

    For cache invalidation: clearing a cache inside the transaction leaves a window in which a
    concurrent request re-caches the OLD data, so the clear must be repeated after the commit."""
    session.info.setdefault("after_commit", []).append(callback)


async def run_after_commit(session: AsyncSession) -> None:
    for callback in session.info.pop("after_commit", []):
        try:
            await callback()
        except Exception:  # a failed cache clear must not turn a committed request into an error
            log.exception("after-commit callback failed")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request: commit when the handler returns, roll back on error."""
    async with request.app.state.session_factory() as session:
        try:
            yield session
            await session.commit()
            await run_after_commit(session)
        except BaseException as exc:
            if isinstance(exc, AppError) and exc.commit_on_error:
                await session.commit()
                await run_after_commit(session)
            else:
                await session.rollback()
                session.info.pop("after_commit", None)
            raise


# scope="function": the commit runs right after the handler returns, before the response is
# sent, so a client never sees a success response for work that failed to commit.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
