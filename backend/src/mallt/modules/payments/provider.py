"""Payment providers. Only the fake one exists until payments are reopened (Razorpay Route)."""

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChargeResult:
    ok: bool
    provider_ref: str


class PaymentProvider(Protocol):
    name: str

    async def charge(self, *, amount_paise: int, reference: str) -> ChargeResult: ...

    async def refund(self, *, amount_paise: int, reference: str) -> ChargeResult: ...


class FakePaymentProvider:
    """Succeeds at once. ``fail_next`` lets tests exercise the failure path."""

    name = "fake"

    def __init__(self) -> None:
        self.fail_next = False
        self.charges: list[tuple[int, str]] = []
        self.refunds: list[tuple[int, str]] = []

    async def charge(self, *, amount_paise: int, reference: str) -> ChargeResult:
        if self.fail_next:
            self.fail_next = False
            return ChargeResult(False, "")
        self.charges.append((amount_paise, reference))
        return ChargeResult(True, f"fake_{uuid.uuid4().hex[:16]}")

    async def refund(self, *, amount_paise: int, reference: str) -> ChargeResult:
        self.refunds.append((amount_paise, reference))
        return ChargeResult(True, f"fake_rf_{uuid.uuid4().hex[:16]}")
