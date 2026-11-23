"""Turns a verified provider webhook into calls on the orders and payments services."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.bus import Bus
from mallt.core.kv import KV
from mallt.modules.orders.service import OrderService
from mallt.modules.payments.service import Kick, PaymentsService
from mallt.modules.payments.zoho import ZohoPaymentProvider

log = logging.getLogger(__name__)

FAILED_MOVEMENTS = {
    "transfer.failed": ("transfer_details", "transfer_id"),
    "transfer_reversal.failed": ("transfer_reversal_details", "transfer_reversal_id"),
    "refund.failed": ("refund", "refund_id"),
}


class ZohoWebhooks:
    def __init__(
        self,
        session: AsyncSession,
        kv: KV,
        bus: Bus,
        provider: ZohoPaymentProvider,
        kick: Kick | None = None,
    ) -> None:
        self.provider = provider
        self.money = PaymentsService(session, kv, provider, kick)
        self.orders = OrderService(session, kv, bus, provider, kick)

    async def handle(self, event: dict[str, Any]) -> None:
        event_id = str(event.get("event_id") or "")
        kind = str(event.get("event_type") or "")
        if not event_id or not await self.money.first_delivery(event_id, kind):
            return  # malformed or already processed
        obj = event.get("event_object") or {}
        if kind == "payment.succeeded" and isinstance(obj.get("payment"), dict):
            await self.orders.on_provider_payment(self.provider.payment_info(obj["payment"]))
        elif kind in FAILED_MOVEMENTS:
            key, ref_field = FAILED_MOVEMENTS[kind]
            details = obj.get(key) or {}
            if ref := details.get(ref_field):
                await self.money.on_movement_failed(
                    str(ref), str(details.get("failure_code") or details.get("failure_reason"))
                )
        else:
            # payment.failed needs no action: the customer may retry within the session, and
            # the sweeper gives the order up when the window closes.
            log.info("zoho webhook %s ignored", kind)
