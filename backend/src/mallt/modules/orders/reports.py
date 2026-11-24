"""Daily sales reports (store and mall) and GST invoices. Reads only; money in integer paise."""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.errors import BadRequest
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.modules.catalog.service import store_profiles
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.orders.enums import StoreOrderStatus as S
from mallt.modules.orders.models import StoreOrder
from mallt.modules.orders.repository import OrdersRepository
from mallt.modules.orders.schemas import (
    BestSellerOut,
    DayOut,
    GstRateOut,
    HourOut,
    InvoiceLineOut,
    InvoiceOut,
    ReportTotalsOut,
    SalesReportOut,
    StoreTotalsOut,
)
from mallt.modules.platform.service import FeatureService
from mallt.modules.tenancy.service import TenancyService

SOLD = frozenset({S.PAID, S.ACCEPTED, S.PREPARING, S.READY, S.PICKED_UP})
# Paid, then given back: rejected, expired, cancelled, and those once refunded.
UNDONE = frozenset({S.REJECTED, S.EXPIRED, S.CANCELLED, S.REFUNDED})
SAC_RESTAURANT = "996331"
MAX_DAYS = 31
BEST_SELLERS = 10


def split_gst(tax_paise: int) -> tuple[int, int]:
    """CGST and SGST halves of an intra-state GST amount (the odd paisa goes to SGST)."""
    cgst = tax_paise // 2
    return cgst, tax_paise - cgst


def _totals(orders: list[StoreOrder]) -> ReportTotalsOut:
    sold = [o for o in orders if o.status in SOLD]
    undone = [o for o in orders if o.status in UNDONE]
    gross = sum(o.total_paise for o in sold)
    tax = sum(o.tax_paise for o in sold)
    fee = sum(o.gateway_fee_paise for o in sold)
    return ReportTotalsOut(
        orders=len(sold),
        items=sum(line.quantity for o in sold for line in o.lines),
        gross_paise=gross,
        tax_paise=tax,
        taxable_paise=gross - tax,
        gateway_fee_paise=fee,
        payout_paise=gross - fee,
        average_order_paise=gross // len(sold) if sold else 0,
        cancelled_orders=len(undone),
        cancelled_paise=sum(o.total_paise for o in undone),
    )


class ReportService:
    def __init__(self, session: AsyncSession, kv: KV) -> None:
        self.session = session
        self.repo = OrdersRepository(session)
        self.authz = AuthzService(session, kv)
        self.tenancy = TenancyService(session, kv)
        self.features = FeatureService(session)

    @staticmethod
    def _range(start: date | None, end: date | None) -> tuple[date, date]:
        today = datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
        start = start or end or today
        end = end or start
        if end < start:
            raise BadRequest("bad_range", "The end date is before the start date.")
        if (end - start).days >= MAX_DAYS:
            raise BadRequest("bad_range", f"Pick at most {MAX_DAYS} days.")
        return start, end

    async def store_sales(
        self, principal: Principal, store_id: uuid.UUID, start: date | None, end: date | None
    ) -> SalesReportOut:
        store = await self.tenancy.get_store(principal, store_id)
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, P.STORE_REPORT_READ, scope)
        await self.features.require("sales_reports")
        first, last = self._range(start, end)
        orders = await self.repo.sales_orders(store_id=store.id, start=first, end=last)
        return await self._report(store.name, first, last, orders, {store.id: store.name})

    async def mall_sales(
        self, principal: Principal, mall_id: uuid.UUID, start: date | None, end: date | None
    ) -> SalesReportOut:
        mall = await self.tenancy.get_mall(principal, mall_id)
        self.authz.require(
            principal, P.STORE_REPORT_READ, Scope.mall(mall.organization_id, mall.id)
        )
        await self.features.require("sales_reports")
        first, last = self._range(start, end)
        orders = await self.repo.sales_orders(mall_id=mall.id, start=first, end=last)
        stores = await self.tenancy.stores_by_ids(list({o.store_id for o in orders}))
        names = {sid: s.name for sid, s in stores.items()}
        return await self._report(mall.name, first, last, orders, names)

    async def _report(
        self,
        name: str,
        start: date,
        end: date,
        orders: list[StoreOrder],
        store_names: dict[uuid.UUID, str],
    ) -> SalesReportOut:
        profiles = await store_profiles(self.session, list({o.store_id for o in orders}))
        sold = [o for o in orders if o.status in SOLD]

        best: dict[tuple[uuid.UUID, str, str], list[int]] = defaultdict(lambda: [0, 0])
        gst: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # rate -> [gross, tax]
        hours = [[0, 0] for _ in range(24)]
        days: dict[date, list[int]] = {
            start + timedelta(days=i): [0, 0] for i in range((end - start).days + 1)
        }
        for o in sold:
            tz = ZoneInfo(profiles[o.store_id].timezone)
            hour = o.created_at.astimezone(tz).hour
            hours[hour][0] += 1
            hours[hour][1] += o.total_paise
            days[o.order_date][0] += 1
            days[o.order_date][1] += o.total_paise
            for line in o.lines:
                key = (o.store_id, line.name, line.variant_name)
                best[key][0] += line.quantity
                best[key][1] += line.line_total_paise
                gst[line.tax_bps][0] += line.line_total_paise
                gst[line.tax_bps][1] += line.tax_paise

        ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0][1]))
        by_store: dict[uuid.UUID, list[StoreOrder]] = defaultdict(list)
        for o in orders:
            by_store[o.store_id].append(o)
        return SalesReportOut(
            start=start,
            end=end,
            name=name,
            totals=_totals(orders),
            best_sellers=[
                BestSellerOut(
                    name=line_name,
                    variant_name=variant,
                    store_name=store_names.get(store_id, ""),
                    quantity=qty,
                    gross_paise=gross,
                )
                for (store_id, line_name, variant), (qty, gross) in ranked[:BEST_SELLERS]
            ],
            hours=[HourOut(hour=h, orders=n, gross_paise=g) for h, (n, g) in enumerate(hours)],
            days=[DayOut(date=d, orders=n, gross_paise=g) for d, (n, g) in days.items()],
            gst=[
                GstRateOut(
                    tax_bps=rate,
                    taxable_paise=gross - tax,
                    cgst_paise=split_gst(tax)[0],
                    sgst_paise=split_gst(tax)[1],
                    tax_paise=tax,
                    gross_paise=gross,
                )
                for rate, (gross, tax) in sorted(gst.items())
            ],
            stores=sorted(
                (
                    StoreTotalsOut(
                        store_id=sid,
                        store_name=store_names.get(sid, ""),
                        totals=_totals(rows),
                    )
                    for sid, rows in by_store.items()
                ),
                key=lambda s: -s.totals.gross_paise,
            ),
        )

    async def store_invoices(
        self, principal: Principal, store_id: uuid.UUID, start: date | None, end: date | None
    ) -> list[InvoiceOut]:
        store = await self.tenancy.get_store(principal, store_id)
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        self.authz.require(principal, P.STORE_REPORT_READ, scope)
        await self.features.require("sales_reports")
        first, last = self._range(start, end)
        orders = await self.repo.sales_orders(store_id=store.id, start=first, end=last)
        profile = (await store_profiles(self.session, [store.id]))[store.id]
        prefix = store.slug.upper().replace("-", "")[:6]
        out = []
        for o in orders:
            if o.status not in SOLD:
                continue
            lines = []
            for line in o.lines:
                cgst, sgst = split_gst(line.tax_paise)
                lines.append(
                    InvoiceLineOut(
                        name=line.name,
                        variant_name=line.variant_name,
                        quantity=line.quantity,
                        unit_price_paise=line.unit_price_paise,
                        tax_bps=line.tax_bps,
                        taxable_paise=line.line_total_paise - line.tax_paise,
                        cgst_paise=cgst,
                        sgst_paise=sgst,
                        total_paise=line.line_total_paise,
                    )
                )
            out.append(
                InvoiceOut(
                    invoice_no=f"{prefix}-{o.order_date:%Y%m%d}-{o.order_no:04d}",
                    order_id=o.id,
                    order_no=o.order_no,
                    date=o.order_date,
                    issued_at=o.created_at,
                    status=o.status.value,
                    store_name=store.name,
                    store_gstin=profile.gstin,
                    store_fssai=profile.fssai,
                    customer_name=o.customer_name,
                    sac=SAC_RESTAURANT,
                    lines=lines,
                    taxable_paise=sum(x.taxable_paise for x in lines),
                    cgst_paise=sum(x.cgst_paise for x in lines),
                    sgst_paise=sum(x.sgst_paise for x in lines),
                    total_paise=sum(x.total_paise for x in lines),
                )
            )
        return out
