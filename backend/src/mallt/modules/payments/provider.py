"""The PaymentProvider interface, and the fake used in dev and tests.

The real provider is Zoho Payments (``zoho.py``). Orders and the money outbox only ever talk to
this interface. Amounts are integer paise everywhere on this side of the interface.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol


class PaymentState(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class StartResult:
    """What the provider said when a checkout asked to be paid."""

    ok: bool
    session_ref: str = ""
    # True when the provider settled at once (the fake). Otherwise the browser has to pay.
    paid: bool = False
    payment_ref: str = ""
    expires_at: datetime | None = None


@dataclass(frozen=True)
class PaymentInfo:
    payment_ref: str
    session_ref: str
    reference: str
    state: PaymentState
    amount_paise: int
    refunded_paise: int = 0


@dataclass(frozen=True)
class MoneyResult:
    """Outcome of a transfer, reversal or refund. ``retryable`` means "may not have happened"."""

    ok: bool
    ref: str = ""
    retryable: bool = False
    error: str = ""


@dataclass(frozen=True)
class AccountDetails:
    account_name: str
    email: str
    pan: str
    mcc: str
    business_description: str
    ifsc: str
    account_number: str


@dataclass(frozen=True)
class AccountInfo:
    account_ref: str
    # Provider's own words, e.g. under_writing_status / transfer_status.
    review_status: str
    transfers_enabled: bool


class ProviderError(Exception):
    """The provider refused or could not be reached. ``retryable`` as in MoneyResult."""

    def __init__(self, message: str, *, retryable: bool = False, code: str = "") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class PaymentProvider(Protocol):
    name: str
    # When True every store in a cart must have an active payout account to be paid.
    requires_payout_accounts: bool

    async def start(
        self, *, amount_paise: int, reference: str, description: str
    ) -> StartResult: ...

    def client_params(
        self, *, session_ref: str, amount_paise: int, description: str
    ) -> dict[str, Any] | None:
        """What the browser needs to open the provider's checkout (None: nothing to do)."""
        ...

    async def get_payment(self, payment_ref: str) -> PaymentInfo | None: ...

    async def find_payment(self, reference: str) -> PaymentInfo | None: ...

    async def transfer(
        self, *, payment_ref: str, account_ref: str, amount_paise: int, reference: str
    ) -> MoneyResult: ...

    async def find_transfer(
        self, *, payment_ref: str, account_ref: str, reference: str
    ) -> str | None: ...

    async def reverse_transfer(
        self, *, transfer_ref: str, amount_paise: int, reference: str
    ) -> MoneyResult: ...

    async def reversed_paise(self, transfer_ref: str) -> int: ...

    async def refund(
        self, *, payment_ref: str, amount_paise: int, reference: str
    ) -> MoneyResult: ...

    async def create_account(self, details: AccountDetails) -> AccountInfo: ...

    async def get_account(self, account_ref: str) -> AccountInfo: ...


@dataclass
class FakePaymentProvider:
    """Pays at once. ``fail_next`` makes the next start/transfer/refund fail (non-retryable);
    ``flaky_next`` makes it fail retryably. Records every movement for tests."""

    name: str = "fake"
    requires_payout_accounts: bool = False
    # False: behave like a real gateway: start() opens a session and the "browser" pays later
    # (tests call ``pay``).
    instant: bool = True
    fail_next: bool = False
    flaky_next: bool = False
    charges: list[tuple[int, str]] = field(default_factory=list)
    refunds: list[tuple[int, str]] = field(default_factory=list)
    transfers: list[tuple[int, str, str]] = field(default_factory=list)  # amount, account, ref
    reversals: list[tuple[int, str]] = field(default_factory=list)
    accounts: dict[str, AccountInfo] = field(default_factory=dict)
    _payments: dict[str, PaymentInfo] = field(default_factory=dict)
    _sessions: dict[str, tuple[int, str]] = field(default_factory=dict)
    _transfer_refs: dict[tuple[str, str, str], str] = field(default_factory=dict)
    _reversed: dict[str, int] = field(default_factory=dict)

    def _take_failure(self) -> MoneyResult | None:
        if self.fail_next:
            self.fail_next = False
            return MoneyResult(False, error="declined")
        if self.flaky_next:
            self.flaky_next = False
            return MoneyResult(False, retryable=True, error="timeout")
        return None

    async def start(self, *, amount_paise: int, reference: str, description: str) -> StartResult:
        if self._take_failure() is not None:
            return StartResult(False)
        ref = f"fake_{uuid.uuid4().hex[:16]}"
        if not self.instant:
            self._sessions[ref] = (amount_paise, reference)
            return StartResult(
                True, session_ref=ref, expires_at=datetime.now(UTC) + timedelta(minutes=15)
            )
        self.charges.append((amount_paise, reference))
        self._payments[ref] = PaymentInfo(ref, ref, reference, PaymentState.SUCCEEDED, amount_paise)
        return StartResult(True, session_ref=ref, paid=True, payment_ref=ref)

    def pay(self, session_ref: str, *, state: PaymentState = PaymentState.SUCCEEDED) -> PaymentInfo:
        """What the provider's checkout does when the customer pays (tests only)."""
        amount, reference = self._sessions[session_ref]
        ref = f"fake_pay_{uuid.uuid4().hex[:12]}"
        info = PaymentInfo(ref, session_ref, reference, state, amount)
        self._payments[ref] = info
        if state is PaymentState.SUCCEEDED:
            self.charges.append((amount, reference))
        return info

    def client_params(
        self, *, session_ref: str, amount_paise: int, description: str
    ) -> dict[str, Any] | None:
        return None

    async def get_payment(self, payment_ref: str) -> PaymentInfo | None:
        return self._payments.get(payment_ref)

    async def find_payment(self, reference: str) -> PaymentInfo | None:
        return next((p for p in self._payments.values() if p.reference == reference), None)

    async def transfer(
        self, *, payment_ref: str, account_ref: str, amount_paise: int, reference: str
    ) -> MoneyResult:
        if (failed := self._take_failure()) is not None:
            return failed
        ref = f"fake_tr_{uuid.uuid4().hex[:16]}"
        self.transfers.append((amount_paise, account_ref, reference))
        self._transfer_refs[(payment_ref, account_ref, reference)] = ref
        return MoneyResult(True, ref)

    async def find_transfer(
        self, *, payment_ref: str, account_ref: str, reference: str
    ) -> str | None:
        return self._transfer_refs.get((payment_ref, account_ref, reference))

    async def reverse_transfer(
        self, *, transfer_ref: str, amount_paise: int, reference: str
    ) -> MoneyResult:
        if (failed := self._take_failure()) is not None:
            return failed
        self.reversals.append((amount_paise, transfer_ref))
        self._reversed[transfer_ref] = self._reversed.get(transfer_ref, 0) + amount_paise
        return MoneyResult(True, f"fake_rv_{uuid.uuid4().hex[:16]}")

    async def reversed_paise(self, transfer_ref: str) -> int:
        return self._reversed.get(transfer_ref, 0)

    async def refund(self, *, payment_ref: str, amount_paise: int, reference: str) -> MoneyResult:
        if (failed := self._take_failure()) is not None:
            return failed
        self.refunds.append((amount_paise, reference))
        if (p := self._payments.get(payment_ref)) is not None:
            self._payments[payment_ref] = PaymentInfo(
                p.payment_ref,
                p.session_ref,
                p.reference,
                p.state,
                p.amount_paise,
                p.refunded_paise + amount_paise,
            )
        return MoneyResult(True, f"fake_rf_{uuid.uuid4().hex[:16]}")

    async def create_account(self, details: AccountDetails) -> AccountInfo:
        info = AccountInfo(f"fake_ca_{uuid.uuid4().hex[:12]}", "approved", True)
        self.accounts[info.account_ref] = info
        return info

    async def get_account(self, account_ref: str) -> AccountInfo:
        if account_ref not in self.accounts:
            raise ProviderError("no such account")
        return self.accounts[account_ref]
