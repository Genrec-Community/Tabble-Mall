from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["health"])


class StatusOut(BaseModel):
    status: str


@router.get("/health")
async def get_health() -> StatusOut:
    return StatusOut(status="ok")
