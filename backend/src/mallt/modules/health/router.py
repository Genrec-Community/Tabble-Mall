from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from mallt.core.db import SessionDep
from mallt.core.errors import AppError

router = APIRouter(prefix="/api/v1", tags=["health"])


class StatusOut(BaseModel):
    status: str


@router.get("/health")
async def get_health() -> StatusOut:
    return StatusOut(status="ok")


@router.get("/ready")
async def get_ready(request: Request, session: SessionDep) -> StatusOut:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise AppError("db_unavailable", title="Service Unavailable", status=503) from exc
    return StatusOut(status="ready")
