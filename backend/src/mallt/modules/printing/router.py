import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from mallt.core.db import SessionDep
from mallt.core.errors import BadRequest
from mallt.modules.iam.deps import KvDep, Staff
from mallt.modules.printing.logo import MAX_UPLOAD_BYTES
from mallt.modules.printing.schemas import (
    AgentCreate,
    AgentCreatedOut,
    AgentOut,
    DesignIn,
    DesignOut,
    DetectedPrinterOut,
    PrinterCreate,
    PrinterOut,
    PrinterUpdate,
    PrintJobOut,
    ScanOut,
)
from mallt.modules.printing.service import PrintingService

router = APIRouter(prefix="/api/v1/stores/{store_id}", tags=["printing"])


def _svc(session: SessionDep, kv: KvDep) -> PrintingService:
    return PrintingService(session, kv)


Svc = Annotated[PrintingService, Depends(_svc, scope="function")]


# ---- agents ----


@router.get("/print-agents")
async def list_agents(store_id: uuid.UUID, principal: Staff, svc: Svc) -> list[AgentOut]:
    return await svc.list_agents(principal, store_id)


@router.post("/print-agents", status_code=status.HTTP_201_CREATED)
async def create_agent(
    store_id: uuid.UUID, body: AgentCreate, principal: Staff, svc: Svc
) -> AgentCreatedOut:
    return await svc.create_agent(principal, store_id, body)


@router.post("/print-agents/{agent_id}/rotate")
async def rotate_agent(
    store_id: uuid.UUID, agent_id: uuid.UUID, principal: Staff, svc: Svc
) -> AgentCreatedOut:
    return await svc.rotate_agent(principal, store_id, agent_id)


@router.post("/print-agents/{agent_id}/revoke")
async def revoke_agent(
    store_id: uuid.UUID, agent_id: uuid.UUID, principal: Staff, svc: Svc
) -> AgentOut:
    return await svc.revoke_agent(principal, store_id, agent_id)


@router.post("/print-agents/{agent_id}/scan", status_code=status.HTTP_202_ACCEPTED)
async def scan_network(
    store_id: uuid.UUID, agent_id: uuid.UUID, principal: Staff, svc: Svc
) -> ScanOut:
    return ScanOut(requested=await svc.request_scan(principal, store_id, agent_id))


@router.get("/detected-printers")
async def detected_printers(
    store_id: uuid.UUID, principal: Staff, svc: Svc
) -> list[DetectedPrinterOut]:
    return await svc.list_detected(principal, store_id)


# ---- printers ----


@router.get("/printers")
async def list_printers(store_id: uuid.UUID, principal: Staff, svc: Svc) -> list[PrinterOut]:
    return await svc.list_printers(principal, store_id)


@router.post("/printers", status_code=status.HTTP_201_CREATED)
async def create_printer(
    store_id: uuid.UUID, body: PrinterCreate, principal: Staff, svc: Svc
) -> PrinterOut:
    return await svc.create_printer(principal, store_id, body)


@router.patch("/printers/{printer_id}")
async def update_printer(
    store_id: uuid.UUID, printer_id: uuid.UUID, body: PrinterUpdate, principal: Staff, svc: Svc
) -> PrinterOut:
    return await svc.update_printer(principal, store_id, printer_id, body)


@router.post("/printers/{printer_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def test_print(
    store_id: uuid.UUID, printer_id: uuid.UUID, principal: Staff, svc: Svc
) -> PrintJobOut:
    return PrintJobOut.model_validate(await svc.test_print(principal, store_id, printer_id))


@router.get("/print-jobs")
async def recent_jobs(
    store_id: uuid.UUID,
    principal: Staff,
    svc: Svc,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[PrintJobOut]:
    return [
        PrintJobOut.model_validate(j) for j in await svc.recent_jobs(principal, store_id, limit)
    ]


# ---- design ----


@router.get("/print-design")
async def get_design(store_id: uuid.UUID, principal: Staff, svc: Svc) -> DesignOut:
    return await svc.get_design(principal, store_id)


@router.put("/print-design")
async def put_design(store_id: uuid.UUID, body: DesignIn, principal: Staff, svc: Svc) -> DesignOut:
    return await svc.put_design(principal, store_id, body)


@router.put("/print-design/logo")
async def put_logo(store_id: uuid.UUID, request: Request, principal: Staff, svc: Svc) -> DesignOut:
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_UPLOAD_BYTES:
        raise BadRequest("logo_too_large", "That image is too large (5 MB maximum).")
    body = b""
    async for chunk in request.stream():  # never buffer more than the limit
        body += chunk
        if len(body) > MAX_UPLOAD_BYTES:
            raise BadRequest("logo_too_large", "That image is too large (5 MB maximum).")
    return await svc.set_logo(principal, store_id, body)


@router.delete("/print-design/logo")
async def delete_logo(store_id: uuid.UUID, principal: Staff, svc: Svc) -> DesignOut:
    return await svc.clear_logo(principal, store_id)


@router.get(
    "/print-design/logo", response_class=Response, responses={200: {"content": {"image/png": {}}}}
)
async def get_logo(store_id: uuid.UUID, principal: Staff, svc: Svc) -> Response:
    return Response(
        content=await svc.logo_png(principal, store_id),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store"},
    )
