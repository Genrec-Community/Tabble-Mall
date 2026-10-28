import base64
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.errors import BadRequest, NotFound
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.catalog.service import print_prefs
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.printing import agents as agent_creds
from mallt.modules.printing import logo as logo_tools
from mallt.modules.printing import payloads
from mallt.modules.printing.enums import JobKind, PrinterConnection, PrinterRole
from mallt.modules.printing.models import (
    DetectedPrinter,
    PrintAgent,
    Printer,
    PrintJob,
    StoreBillSettings,
)
from mallt.modules.printing.repository import PrintingRepository
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
    SlipOptions,
)
from mallt.modules.printing.types import PrintableOrder, PrintPrefs
from mallt.modules.tenancy.models import Store
from mallt.modules.tenancy.service import TenancyService

log = logging.getLogger(__name__)
ONLINE_WITHIN = timedelta(seconds=60)
THERMAL_HINTS = ("pos", "tm-", "rp", "epson", "xprinter", "tsp", "thermal", "receipt", "58", "80")
SCAN_FLAG_TTL_S = 120
LAN_KINDS = frozenset({PrinterConnection.LAN})
LOCAL_KINDS = frozenset(
    {PrinterConnection.USB, PrinterConnection.BLUETOOTH, PrinterConnection.SYSTEM}
)


def scan_key(agent_id: uuid.UUID) -> str:
    return f"printing:scan:{agent_id}"


class PrintingService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.session = session
        self.kv = kv
        self.repo = PrintingRepository(session)
        self.tenancy = TenancyService(session, kv)
        self.authz = AuthzService(session, kv)
        self.audit = AuditService(session)

    # ---- access ----

    async def _store(
        self, principal: Principal, store_id: uuid.UUID, permission: P, *, write: bool = False
    ) -> tuple[Store, Scope]:
        store = await self.tenancy.get_store(principal, store_id)  # unseen tenants: 404
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, permission, scope)
        if write:
            await self.tenancy.assert_operational(principal, scope)
        return store, scope

    async def _record(
        self,
        principal: Principal,
        action: str,
        target: str,
        target_id: uuid.UUID,
        scope: Scope,
        after: dict[str, Any] | None = None,
    ) -> None:
        await self.audit.record(
            actor=Actor(ActorType.STAFF, principal.staff_id),
            action=action,
            target_type=target,
            target_id=target_id,
            scope=scope,
            before=None,
            after=after,
        )

    @staticmethod
    def _owned(store: Store) -> dict[str, uuid.UUID]:
        return {
            "organization_id": store.organization_id,
            "mall_id": store.mall_id,
            "store_id": store.id,
        }

    # ---- agents ----

    @staticmethod
    def _agent_out(agent: PrintAgent) -> AgentOut:
        out = AgentOut.model_validate(agent)
        out.online = bool(
            agent.is_active
            and agent.last_seen_at
            and datetime.now(UTC) - agent.last_seen_at < ONLINE_WITHIN
        )
        return out

    async def list_agents(self, principal: Principal, store_id: uuid.UUID) -> list[AgentOut]:
        store, _ = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE)
        return [self._agent_out(a) for a in await self.repo.agents(store.id)]

    async def create_agent(
        self, principal: Principal, store_id: uuid.UUID, data: AgentCreate
    ) -> AgentCreatedOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        agent_id = uuid.uuid4()
        token, token_hash, prefix = agent_creds.issue(agent_id)
        agent = PrintAgent(
            id=agent_id,
            name=data.name,
            token_hash=token_hash,
            token_prefix=prefix,
            **self._owned(store),
        )
        await self.repo.add_unique(agent, f"A print agent named {data.name!r} already exists.")
        await self._record(
            principal, "print_agent.paired", "print_agent", agent.id, scope, {"name": agent.name}
        )
        return AgentCreatedOut(agent=self._agent_out(agent), token=token)

    async def rotate_agent(
        self, principal: Principal, store_id: uuid.UUID, agent_id: uuid.UUID
    ) -> AgentCreatedOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        agent = await self.repo.store_agent(store.id, agent_id)
        if agent is None:
            raise NotFound("not_found", "Not found.")
        token, agent.token_hash, agent.token_prefix = agent_creds.issue(agent.id)
        agent.is_active = True
        await self.session.flush()
        await self._record(principal, "print_agent.rotated", "print_agent", agent.id, scope)
        return AgentCreatedOut(agent=self._agent_out(agent), token=token)

    async def revoke_agent(
        self, principal: Principal, store_id: uuid.UUID, agent_id: uuid.UUID
    ) -> AgentOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        agent = await self.repo.store_agent(store.id, agent_id)
        if agent is None:
            raise NotFound("not_found", "Not found.")
        agent.is_active = False
        await self.session.flush()
        await self._record(principal, "print_agent.revoked", "print_agent", agent.id, scope)
        return self._agent_out(agent)

    async def request_scan(
        self, principal: Principal, store_id: uuid.UUID, agent_id: uuid.UUID
    ) -> bool:
        store, _ = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        agent = await self.repo.store_agent(store.id, agent_id)
        if agent is None or not agent.is_active:
            raise NotFound("not_found", "Not found.")
        await self.kv.set(scan_key(agent.id), "1", SCAN_FLAG_TTL_S)
        return True

    # ---- detected printers (reported by the agent) ----

    async def list_detected(
        self, principal: Principal, store_id: uuid.UUID
    ) -> list[DetectedPrinterOut]:
        store, _ = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE)
        return [
            DetectedPrinterOut(
                agent_id=d.agent_id,
                agent_name=name,
                key=d.key,
                name=d.name,
                connection=d.connection,
                target=d.target,
                driver=d.driver,
                is_default=d.is_default,
                likely_thermal=d.likely_thermal,
            )
            for d, name in await self.repo.detected(store.id)
        ]

    async def record_detected(
        self, agent: PrintAgent, items: list[dict[str, Any]], *, scope: str = "local"
    ) -> None:
        """Called from the agent socket with whatever the agent found (untrusted input).

        ``scope`` "local" (OS queues, USB, serial) or "lan" (an on-demand network scan); a report
        replaces only its own scope."""
        wanted = LAN_KINDS if scope == "lan" else LOCAL_KINDS
        rows: dict[str, DetectedPrinter] = {}
        for raw in items[:200]:
            try:
                connection = PrinterConnection(raw["connection"])
                key, name, target = (
                    str(raw["key"])[:200],
                    str(raw["name"])[:120],
                    str(raw["target"])[:255],
                )
            except (KeyError, ValueError, TypeError):
                continue
            if connection not in wanted:
                continue
            rows[key] = DetectedPrinter(
                agent_id=agent.id,
                organization_id=agent.organization_id,
                mall_id=agent.mall_id,
                store_id=agent.store_id,
                key=key,
                name=name,
                connection=connection,
                target=target,
                driver=str(raw["driver"])[:120] if raw.get("driver") else None,
                is_default=bool(raw.get("is_default")),
                likely_thermal=any(h in name.lower() for h in THERMAL_HINTS),
            )
        await self.repo.replace_detected(agent, list(rows.values()), scope=set(wanted))

    # ---- printers ----

    async def list_printers(self, principal: Principal, store_id: uuid.UUID) -> list[PrinterOut]:
        store, _ = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE)
        return [PrinterOut.model_validate(p) for p in await self.repo.printers(store.id)]

    async def create_printer(
        self, principal: Principal, store_id: uuid.UUID, data: PrinterCreate
    ) -> PrinterOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        printer = Printer(
            name=data.name,
            role=data.role,
            connection=data.connection,
            target=data.target,
            paper_width=data.paper_width,
            layout=data.layout.stored() if data.layout else {},
            **self._owned(store),
        )
        await self.repo.add_unique(printer, f"A printer named {data.name!r} already exists.")
        await self._record(
            principal,
            "printer.created",
            "printer",
            printer.id,
            scope,
            {"name": printer.name, "role": printer.role.value},
        )
        return PrinterOut.model_validate(printer)

    async def update_printer(
        self, principal: Principal, store_id: uuid.UUID, printer_id: uuid.UUID, data: PrinterUpdate
    ) -> PrinterOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        printer = await self.repo.printer(store.id, printer_id)
        if printer is None:
            raise NotFound("not_found", "Not found.")
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        if data.layout is not None:
            changes["layout"] = data.layout.stored()
        for field, value in changes.items():
            setattr(printer, field, value)
        await self.repo.flush_unique(f"A printer named {printer.name!r} already exists.")
        await self._record(
            principal,
            "printer.updated",
            "printer",
            printer.id,
            scope,
            {k: v for k, v in changes.items() if k != "layout"},
        )
        return PrinterOut.model_validate(printer)

    async def test_print(
        self, principal: Principal, store_id: uuid.UUID, printer_id: uuid.UUID
    ) -> PrintJob:
        store, _ = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        printer = await self.repo.printer(store.id, printer_id)
        if printer is None:
            raise NotFound("not_found", "Not found.")
        if not printer.is_active:
            raise BadRequest("printer_inactive", "Turn the printer on before printing a test.")
        job = PrintJob(
            printer_id=printer.id,
            kind=JobKind.TEST,
            payload=payloads.test_payload(printer.name, store.name, printer.paper_width),
            **self._owned(store),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def recent_jobs(
        self, principal: Principal, store_id: uuid.UUID, limit: int
    ) -> list[PrintJob]:
        store, _ = await self._store(principal, store_id, P.STORE_ORDER_PRINT)
        return await self.repo.recent_jobs(store.id, limit)

    # ---- design ----

    @staticmethod
    def _design_out(row: StoreBillSettings | None) -> DesignOut:
        if row is None:
            return DesignOut(
                header_name=None,
                header_address=None,
                header_phone=None,
                header_extra=None,
                footer_text=None,
                options=SlipOptions(),
                has_logo=False,
            )
        return DesignOut(
            header_name=row.header_name,
            header_address=row.header_address,
            header_phone=row.header_phone,
            header_extra=row.header_extra,
            footer_text=row.footer_text,
            options=SlipOptions.model_validate(row.options or {}),
            has_logo=row.logo_png is not None,
        )

    async def get_design(self, principal: Principal, store_id: uuid.UUID) -> DesignOut:
        store, _ = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE)
        return self._design_out(await self.repo.design(store.id))

    async def _design_row(self, store: Store) -> StoreBillSettings:
        row = await self.repo.design(store.id)
        if row is None:
            row = StoreBillSettings(options={}, **self._owned(store))
            self.session.add(row)
            await self.session.flush()
        return row

    async def put_design(
        self, principal: Principal, store_id: uuid.UUID, data: DesignIn
    ) -> DesignOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        row = await self._design_row(store)
        row.header_name = data.header_name or None
        row.header_address = data.header_address or None
        row.header_phone = data.header_phone or None
        row.header_extra = data.header_extra or None
        row.footer_text = data.footer_text or None
        row.options = data.options.stored()
        await self.session.flush()
        await self._record(principal, "print_design.updated", "store", store.id, scope)
        return self._design_out(row)

    async def set_logo(self, principal: Principal, store_id: uuid.UUID, raw: bytes) -> DesignOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        png = logo_tools.normalise(raw)
        row = await self._design_row(store)
        row.logo_png = png
        await self.session.flush()
        await self._record(principal, "print_logo.set", "store", store.id, scope)
        return self._design_out(row)

    async def clear_logo(self, principal: Principal, store_id: uuid.UUID) -> DesignOut:
        store, scope = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE, write=True)
        row = await self._design_row(store)
        row.logo_png = None
        await self.session.flush()
        await self._record(principal, "print_logo.cleared", "store", store.id, scope)
        return self._design_out(row)

    async def logo_png(self, principal: Principal, store_id: uuid.UUID) -> bytes:
        store, _ = await self._store(principal, store_id, P.STORE_PRINTER_MANAGE)
        row = await self.repo.design(store.id)
        if row is None or row.logo_png is None:
            raise NotFound("not_found", "Not found.")
        return row.logo_png

    # ---- dispatch (called by the orders module; never raises into an order) ----

    async def on_order_status(self, order: PrintableOrder, status: str) -> None:
        """Queue slips for a status change according to the store's rules. Best effort: a
        printing problem must never affect the order, so failures are logged and swallowed."""
        try:
            # Everything, including reading the store's rules, runs in a savepoint: a SQL error
            # aborts a Postgres transaction, and this must never take the order's own work with it.
            async with self.session.begin_nested():
                prefs = await print_prefs(self.session, order.store_id)
                if not prefs.auto_print:
                    return
                pp = PrintPrefs(**prefs.__dict__)
                if status == pp.kot_when:
                    await self.queue_ticket(order, pp)
                if status == pp.bill_when:
                    await self.queue_bill(order, pp)
        except Exception:
            log.exception("could not queue print jobs for order %s", order.id)

    async def _design_for(self, order: PrintableOrder) -> StoreBillSettings | None:
        return await self.repo.design(order.store_id)

    async def queue_ticket(
        self, order: PrintableOrder, prefs: PrintPrefs, *, revision: int | None = None
    ) -> int:
        printers = await self.repo.printers_by_role(order.store_id, PrinterRole.KITCHEN)
        if not printers:  # no kitchen printer: the counter printer prints the KOT
            printers = await self.repo.printers_by_role(order.store_id, PrinterRole.COUNTER)
        design = await self._design_for(order)
        options = (design.options if design else None) or {}
        rev = (
            await self.repo.next_revision(order.id, JobKind.TICKET)
            if revision is None
            else revision
        )
        queued = 0
        for printer in printers:
            payload = payloads.ticket_payload(order, prefs, options, revision=rev)
            job = PrintJob(
                printer_id=printer.id,
                store_order_id=order.id,
                kind=JobKind.TICKET,
                revision=rev,
                payload=payload,
                organization_id=order.organization_id,
                mall_id=order.mall_id,
                store_id=order.store_id,
            )
            if await self.repo.insert_job(job):
                queued += 1
        return queued

    async def queue_bill(self, order: PrintableOrder, prefs: PrintPrefs) -> int:
        printers = await self.repo.printers_by_role(order.store_id, PrinterRole.COUNTER)
        if not printers:
            return 0
        design = await self._design_for(order)
        options = (design.options if design else None) or {}
        header = {
            "name": (design.header_name if design and design.header_name else order.store_name),
            "address": design.header_address if design else None,
            "phone": design.header_phone if design else None,
            "extra": design.header_extra if design else None,
        }
        footer = design.footer_text if design and design.footer_text is not None else "Thank you"
        copy = await self.repo.bill_copies(order.id) + 1
        queued = 0
        for printer in printers:
            logo = (
                logo_tools.raster_for(design.logo_png, printer.paper_width)
                if design and design.logo_png and options.get("show_logo", True)
                else None
            )
            payload = payloads.bill_payload(
                order, prefs, header, footer, options, copy_number=copy, logo=logo
            )
            job = PrintJob(
                printer_id=printer.id,
                store_order_id=order.id,
                kind=JobKind.BILL,
                revision=copy - 1,
                payload=payload,
                organization_id=order.organization_id,
                mall_id=order.mall_id,
                store_id=order.store_id,
            )
            if await self.repo.insert_job(job):
                queued += 1
        return queued

    async def reprint(self, principal: Principal, order: PrintableOrder, what: str) -> int:
        """Staff pressed Reprint. Raises BadRequest when there is nowhere to print."""
        _, _ = await self._store(principal, order.store_id, P.STORE_ORDER_PRINT, write=True)
        prefs = PrintPrefs(**(await print_prefs(self.session, order.store_id)).__dict__)
        queued = (
            await self.queue_ticket(order, prefs)
            if what == "ticket"
            else await self.queue_bill(order, prefs)
        )
        if queued == 0:
            raise BadRequest("no_printer", "No active printer is set up for this.")
        return queued


def decode_logo_for_test(raster: dict[str, Any]) -> bytes:  # pragma: no cover - test helper
    return base64.b64decode(raster["data"])
