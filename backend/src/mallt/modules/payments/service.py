"""Payments domain: store payout accounts, the money outbox (transfers, reversals, refunds) and
the append-only ledger. Orders talk to this service; it never imports the orders module."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.db import defer_after_commit
from mallt.core.enums import ActorType
from mallt.core.errors import BadRequest, Conflict, NotFound
from mallt.core.kv import KV
from mallt.core.rbac import P, Scope
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.iam.authz import AuthzService, Principal
from mallt.modules.payments.enums import LedgerKind, PayoutStatus, TaskKind, TaskStatus
from mallt.modules.payments.models import LedgerEntry, PaymentTask, PayoutAccount
from mallt.modules.payments.provider import (
    AccountDetails,
    AccountInfo,
    MoneyResult,
    PaymentProvider,
    ProviderError,
)
from mallt.modules.payments.repository import PaymentsRepository
from mallt.modules.payments.schemas import (
    PaymentsOverviewOut,
    PaymentTaskOut,
    PayoutAccountCreate,
    PayoutAccountOut,
    StorePayoutRowOut,
    StorePayoutsOut,
    StorePayoutSummaryOut,
)
from mallt.modules.tenancy.service import TenancyService

log = logging.getLogger(__name__)

PROVIDER_REPORTED_FAILED = "Reported failed by the provider"

Kick = Callable[[], Awaitable[None]]
MAX_ATTEMPTS = 12
REJECTED_REVIEW = frozenset({"rejected", "declined", "disabled", "inactive", "suspended"})


def backoff(attempts: int) -> timedelta:
    """30 s, 1 min, 2 min ... capped at an hour."""
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


@dataclass(frozen=True)
class Owner:
    organization_id: uuid.UUID
    mall_id: uuid.UUID
    store_id: uuid.UUID
    order_label: str | None = None  # shown on the payouts and admin screens


def _mask(value: str) -> str:
    return "•" * 4 + value[-4:]


class PaymentsService:
    def __init__(
        self,
        session: AsyncSession,
        kv: KV,
        provider: PaymentProvider,
        kick: Kick | None = None,
    ) -> None:
        self.session = session
        self.kv = kv
        self.provider = provider
        self.kick = kick
        self.repo = PaymentsRepository(session)
        self._kicked = False

    # ------------------------------------------------------------------ used by orders

    async def unpayable_stores(self, store_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Stores in ``store_ids`` that cannot be paid yet (no active payout account)."""
        if not self.provider.requires_payout_accounts:
            return set()
        active = await self.repo.active_accounts(store_ids)
        return {s for s in store_ids if s not in active}

    def record(
        self,
        kind: LedgerKind,
        *,
        organization_id: uuid.UUID,
        mall_id: uuid.UUID,
        customer_order_id: uuid.UUID,
        amount_paise: int,
        provider_ref: str = "",
        store_id: uuid.UUID | None = None,
        store_order_id: uuid.UUID | None = None,
    ) -> None:
        self.session.add(
            LedgerEntry(
                organization_id=organization_id,
                mall_id=mall_id,
                store_id=store_id,
                customer_order_id=customer_order_id,
                store_order_id=store_order_id,
                kind=kind,
                amount_paise=amount_paise,
                provider=self.provider.name,
                provider_ref=provider_ref,
            )
        )

    def _task(
        self,
        kind: TaskKind,
        owner: Owner,
        customer_order_id: uuid.UUID,
        store_order_id: uuid.UUID,
        payment_ref: str,
        amount_paise: int,
        account_ref: str | None = None,
    ) -> PaymentTask:
        task = PaymentTask(
            organization_id=owner.organization_id,
            mall_id=owner.mall_id,
            store_id=owner.store_id,
            customer_order_id=customer_order_id,
            store_order_id=store_order_id,
            kind=kind,
            status=TaskStatus.PENDING,
            provider=self.provider.name,
            amount_paise=amount_paise,
            payment_ref=payment_ref,
            account_ref=account_ref,
            order_label=owner.order_label,
            attempts=0,
            next_attempt_at=datetime.now(UTC),
        )
        self.session.add(task)
        self._schedule_kick()
        return task

    def _schedule_kick(self) -> None:
        if self.kick is not None and not self._kicked:
            self._kicked = True
            defer_after_commit(self.session, self.kick)

    async def queue_transfer(
        self,
        owner: Owner,
        *,
        customer_order_id: uuid.UUID,
        store_order_id: uuid.UUID,
        payment_ref: str,
        amount_paise: int,
    ) -> None:
        """Send a store its share. Runs after commit; never blocks the caller."""
        if amount_paise <= 0:
            await self.session.flush()
            return
        account = (await self.repo.active_accounts([owner.store_id])).get(owner.store_id)
        account_ref = account.account_ref if account else None
        task = self._task(
            TaskKind.TRANSFER,
            owner,
            customer_order_id,
            store_order_id,
            payment_ref,
            amount_paise,
            account_ref,
        )
        if account_ref is None and self.provider.requires_payout_accounts:
            task.status = TaskStatus.FAILED
            task.last_error = "The store has no active payout account"
        await self.session.flush()

    async def queue_refund(
        self,
        owner: Owner,
        *,
        customer_order_id: uuid.UUID,
        store_order_id: uuid.UUID,
        payment_ref: str,
        amount_paise: int,
    ) -> None:
        """Refund one store order. A transfer that never ran is cancelled; one that ran (or may
        have) is reversed first. Other stores' parts of the same payment are untouched.

        `amount_paise` is what the store received (its share minus the gateway fee): the fee is
        not refunded (owner decision, 2026-11-24), so neither MallT nor the store pays it."""
        for task in await self.repo.tasks_for_order(customer_order_id, lock=True):
            if task.store_order_id != store_order_id or task.kind is not TaskKind.TRANSFER:
                continue
            if task.status is TaskStatus.PENDING and task.attempts == 0:
                task.status = TaskStatus.CANCELLED
                task.last_error = "Refunded before the transfer ran"
            elif task.status in (TaskStatus.PENDING, TaskStatus.DONE):
                self._task(
                    TaskKind.REVERSAL,
                    owner,
                    customer_order_id,
                    store_order_id,
                    payment_ref,
                    task.amount_paise,
                    task.account_ref,
                )
        if amount_paise > 0:
            self._task(
                TaskKind.REFUND, owner, customer_order_id, store_order_id, payment_ref, amount_paise
            )
        await self.session.flush()

    # ------------------------------------------------------------------ the outbox worker

    async def process_next(self) -> bool:
        """Run the next due money task. Returns False when nothing is due. The caller commits."""
        task = await self.repo.next_due_task()
        if task is None:
            return False
        try:
            result = await self._execute(task)
        except ProviderError as exc:  # a lookup failed: try again later
            result = MoneyResult(False, retryable=exc.retryable, error=str(exc))
        if result is None:
            return True  # finished without a provider call (cancelled / already done)
        task.attempts += 1
        if result.ok:
            self._finish(task, result.ref)
        elif result.retryable and task.attempts < MAX_ATTEMPTS:
            task.last_error = result.error[:500]
            task.next_attempt_at = datetime.now(UTC) + backoff(task.attempts)
        else:
            task.status = TaskStatus.FAILED
            task.last_error = result.error[:500] or "failed"
            log.error("money task %s (%s) failed: %s", task.id, task.kind, task.last_error)
        await self.session.flush()
        return True

    def _finish(self, task: PaymentTask, ref: str) -> None:
        task.status = TaskStatus.DONE
        task.provider_ref = ref
        task.last_error = None
        kind, sign = {
            TaskKind.TRANSFER: (LedgerKind.TRANSFER, 1),
            TaskKind.REVERSAL: (LedgerKind.TRANSFER_REVERSAL, -1),
            TaskKind.REFUND: (LedgerKind.REFUND, -1),
        }[task.kind]
        self.record(
            kind,
            organization_id=task.organization_id,
            mall_id=task.mall_id,
            store_id=task.store_id,
            customer_order_id=task.customer_order_id,
            store_order_id=task.store_order_id,
            amount_paise=sign * task.amount_paise,
            provider_ref=ref,
        )

    async def _execute(self, task: PaymentTask) -> MoneyResult | None:
        reference = f"so:{task.store_order_id}"
        if task.kind is TaskKind.TRANSFER:
            account_ref = task.account_ref or "unlinked"
            if task.attempts:  # an earlier attempt may have gone through
                found = await self.provider.find_transfer(
                    payment_ref=task.payment_ref, account_ref=account_ref, reference=reference
                )
                if found:
                    return MoneyResult(True, found)
            return await self.provider.transfer(
                payment_ref=task.payment_ref,
                account_ref=account_ref,
                amount_paise=task.amount_paise,
                reference=reference,
            )
        if task.kind is TaskKind.REVERSAL:
            transfer = next(
                (
                    t
                    for t in await self.repo.tasks_for_order(task.customer_order_id)
                    if t.kind is TaskKind.TRANSFER and t.store_order_id == task.store_order_id
                ),
                None,
            )
            if transfer is None or transfer.status is not TaskStatus.DONE:
                task.status = TaskStatus.CANCELLED
                task.last_error = "Nothing was transferred"
                await self.session.flush()
                return None
            transfer_ref = transfer.provider_ref or ""
            if task.attempts and await self.provider.reversed_paise(transfer_ref) >= (
                task.amount_paise
            ):
                return MoneyResult(True, f"reversal-of:{transfer_ref}")
            return await self.provider.reverse_transfer(
                transfer_ref=transfer_ref, amount_paise=task.amount_paise, reference=reference
            )
        # refund
        if task.baseline_paise is None or task.attempts:
            payment = await self.provider.get_payment(task.payment_ref)
            refunded = payment.refunded_paise if payment else 0
            if task.baseline_paise is None:
                task.baseline_paise = refunded
            elif refunded >= task.baseline_paise + task.amount_paise:
                return MoneyResult(True, f"refund-of:{task.payment_ref}")
        return await self.provider.refund(
            payment_ref=task.payment_ref, amount_paise=task.amount_paise, reference=reference
        )

    async def on_movement_failed(self, provider_ref: str, error: str = "") -> None:
        """The provider accepted a transfer, reversal or refund but later reported it failed:
        mark the task for a person and correct the ledger (append-only: an opposite entry)."""
        task = await self.repo.task_by_ref(self.provider.name, provider_ref)
        if task is None or task.status is not TaskStatus.DONE:
            return
        task.status = TaskStatus.FAILED
        task.last_error = f"{PROVIDER_REPORTED_FAILED}: {error}"[:500]
        kind, sign = {
            TaskKind.TRANSFER: (LedgerKind.TRANSFER, -1),
            TaskKind.REVERSAL: (LedgerKind.TRANSFER_REVERSAL, 1),
            TaskKind.REFUND: (LedgerKind.REFUND, 1),
        }[task.kind]
        self.record(
            kind,
            organization_id=task.organization_id,
            mall_id=task.mall_id,
            store_id=task.store_id,
            customer_order_id=task.customer_order_id,
            store_order_id=task.store_order_id,
            amount_paise=sign * task.amount_paise,
            provider_ref=provider_ref,
        )
        log.error("money task %s reported failed by the provider: %s", task.id, error)
        await self.session.flush()

    async def first_delivery(self, event_id: str, event_type: str) -> bool:
        return await self.repo.first_delivery(self.provider.name, event_id, event_type)

    # ------------------------------------------------------------------ payout accounts

    async def _store_scope(
        self, principal: Principal, store_id: uuid.UUID, permission: P
    ) -> tuple[Scope, TenancyService]:
        tenancy = TenancyService(self.session, self.kv)
        store = await tenancy.get_store(principal, store_id)  # unseen tenants: 404
        scope = Scope.store(store.organization_id, store.mall_id, store.id)
        AuthzService(self.session, self.kv).require(principal, permission, scope)
        return scope, tenancy

    @staticmethod
    def _out(account: PayoutAccount) -> PayoutAccountOut:
        return PayoutAccountOut(
            store_id=account.store_id,
            provider=account.provider,
            account_name=account.account_name,
            email=account.email,
            pan_masked=_mask(account.pan_last4),
            bank_masked=_mask(account.bank_last4),
            ifsc=account.ifsc,
            mcc=account.mcc,
            status=account.status,
            review_status=account.review_status,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    @staticmethod
    def _apply(account: PayoutAccount, info: AccountInfo) -> None:
        account.review_status = info.review_status
        if info.transfers_enabled:
            account.status = PayoutStatus.ACTIVE
        elif info.review_status.lower() in REJECTED_REVIEW:
            account.status = PayoutStatus.DISABLED
        else:
            account.status = PayoutStatus.PENDING

    async def get_payout_account(
        self, principal: Principal, store_id: uuid.UUID
    ) -> PayoutAccountOut:
        await self._store_scope(principal, store_id, P.STORE_KYC_SUBMIT)
        account = await self.repo.account_for_store(store_id)
        if account is None:
            raise NotFound("no_payout_account", "This store has not added a payout account yet.")
        return self._out(account)

    async def submit_payout_account(
        self, principal: Principal, store_id: uuid.UUID, data: PayoutAccountCreate
    ) -> PayoutAccountOut:
        scope, tenancy = await self._store_scope(principal, store_id, P.STORE_KYC_SUBMIT)
        await tenancy.assert_operational(principal, scope)
        account = await self.repo.account_for_store(store_id)
        if account is not None and account.status is PayoutStatus.ACTIVE:
            raise Conflict(
                "payout_account_active",
                "This store's payout account is already active. Contact MallT support to change"
                " the bank account.",
            )
        try:
            info = await self.provider.create_account(
                AccountDetails(
                    account_name=data.account_name,
                    email=data.email,
                    pan=data.pan,
                    mcc=data.mcc,
                    business_description=data.business_description,
                    ifsc=data.ifsc,
                    account_number=data.account_number,
                )
            )
        except ProviderError as exc:
            log.warning("payout account rejected for store %s: %s", store_id, exc.code)
            raise BadRequest(
                "payout_account_rejected",
                "The payment provider did not accept these details. Check them and try again.",
            ) from exc
        assert scope.organization_id and scope.mall_id  # noqa: S101 - a store scope carries both
        if account is None:
            account = PayoutAccount(
                organization_id=scope.organization_id, mall_id=scope.mall_id, store_id=store_id
            )
            self.session.add(account)
        account.provider = self.provider.name
        account.account_ref = info.account_ref
        account.account_name = data.account_name
        account.email = data.email
        account.pan_last4 = data.pan[-4:]
        account.bank_last4 = data.account_number[-4:]
        account.ifsc = data.ifsc
        account.mcc = data.mcc
        self._apply(account, info)
        await self.session.flush()
        await self.session.refresh(account)
        await AuditService(self.session).record(
            actor=Actor(ActorType.STAFF, principal.staff_id),
            action="payout_account.submit",
            target_type="payout_account",
            target_id=account.id,
            scope=scope,
            before=None,
            after={"status": account.status.value, "bank": _mask(account.bank_last4)},
        )
        return self._out(account)

    async def refresh_payout_account(
        self, principal: Principal, store_id: uuid.UUID
    ) -> PayoutAccountOut:
        scope, _ = await self._store_scope(principal, store_id, P.STORE_KYC_SUBMIT)
        account = await self.repo.account_for_store(store_id)
        if account is None:
            raise NotFound("no_payout_account", "This store has not added a payout account yet.")
        try:
            info = await self.provider.get_account(account.account_ref)
        except ProviderError as exc:
            raise Conflict(
                "provider_unavailable", "Could not reach the payment provider. Try again."
            ) from exc
        before = account.status
        self._apply(account, info)
        await self.session.flush()
        await self.session.refresh(account)
        if account.status is not before:
            await AuditService(self.session).record(
                actor=Actor(ActorType.STAFF, principal.staff_id),
                action="payout_account.status",
                target_type="payout_account",
                target_id=account.id,
                scope=scope,
                before={"status": before.value},
                after={"status": account.status.value},
            )
        return self._out(account)

    async def overview(self, principal: Principal, limit: int = 100) -> PaymentsOverviewOut:
        AuthzService(self.session, self.kv).require(
            principal, P.PLATFORM_KYC_APPROVE, Scope.platform()
        )
        accounts = await self.repo.list_accounts(limit)
        failed = await self.repo.failed_tasks(limit)
        retrying = await self.repo.retrying_tasks(limit)
        stores = await TenancyService(self.session, self.kv).stores_by_ids(
            list({t.store_id for t in failed + retrying})
        )

        def out(t: PaymentTask) -> PaymentTaskOut:
            row = PaymentTaskOut.model_validate(t)
            store = stores.get(t.store_id)
            return row.model_copy(update={"store_name": store.name if store else None})

        return PaymentsOverviewOut(
            accounts=[self._out(a) for a in accounts],
            failed_tasks=[out(t) for t in failed],
            retrying_tasks=[out(t) for t in retrying],
        )

    async def retry_task(self, principal: Principal, task_id: uuid.UUID) -> PaymentTaskOut:
        """A person sorted out the cause (e.g. topped up a store's Zoho balance): try again."""
        AuthzService(self.session, self.kv).require(
            principal, P.PLATFORM_KYC_APPROVE, Scope.platform()
        )
        task = await self.repo.task_for_update(task_id)
        if task is None:
            raise NotFound("not_found", "Not found.")
        if task.status is not TaskStatus.FAILED:
            raise Conflict("not_failed", "Only a failed money task can be retried.")
        before = {"status": task.status.value, "attempts": task.attempts}
        if (task.last_error or "").startswith(PROVIDER_REPORTED_FAILED):
            # The provider said this movement failed, so a fresh one is needed.
            task.attempts = 0
            task.provider_ref = None
        else:
            # Keep attempts > 0 when there were some: the worker first checks whether an earlier
            # attempt went through, so money never moves twice. Allow a full set of retries.
            task.attempts = min(task.attempts, 1)
        task.status = TaskStatus.PENDING
        task.next_attempt_at = datetime.now(UTC)
        await AuditService(self.session).record(
            actor=Actor(ActorType.STAFF, principal.staff_id),
            action="payment_task.retry",
            target_type="payment_task",
            target_id=task.id,
            scope=Scope.platform(),
            before=before,
            after={"status": task.status.value, "attempts": task.attempts},
        )
        await self.session.flush()
        await self.session.refresh(task)
        self._schedule_kick()
        return PaymentTaskOut.model_validate(task)

    async def store_payouts(
        self, principal: Principal, store_id: uuid.UUID, before: uuid.UUID | None, limit: int
    ) -> StorePayoutsOut:
        """What the store was paid, order by order, and the fees on it."""
        await self._store_scope(principal, store_id, P.STORE_KYC_SUBMIT)
        transfers = await self.repo.store_transfers(store_id, before, limit + 1)
        page = transfers[:limit]
        ids = [t.store_order_id for t in page]
        fees = await self.repo.fees_for(ids)
        refunds: dict[uuid.UUID, PaymentTask] = {}
        for t in await self.repo.tasks_for_store_orders(ids):
            if t.kind is TaskKind.REFUND:
                refunds[t.store_order_id] = t
        items = []
        for t in page:
            fee = fees.get(t.store_order_id, 0)
            refund = refunds.get(t.store_order_id)
            items.append(
                StorePayoutRowOut(
                    store_order_id=t.store_order_id,
                    order_label=t.order_label,
                    created_at=t.created_at,
                    order_total_paise=t.amount_paise + fee,
                    fee_paise=fee,
                    payout_paise=t.amount_paise,
                    transfer_status=t.status,
                    refund_paise=refund.amount_paise if refund else None,
                    refund_status=refund.status if refund else None,
                )
            )
        ledger = await self.repo.store_ledger_totals(store_id)
        tasks = await self.repo.store_task_totals(store_id)
        transfer_total = sum(v for (k, _), v in tasks.items() if k is TaskKind.TRANSFER)
        summary = StorePayoutSummaryOut(
            sales_paise=transfer_total + ledger.get(LedgerKind.GATEWAY_FEE, 0),
            fees_paise=ledger.get(LedgerKind.GATEWAY_FEE, 0),
            paid_out_paise=ledger.get(LedgerKind.TRANSFER, 0),
            on_the_way_paise=tasks.get((TaskKind.TRANSFER, TaskStatus.PENDING), 0),
            failed_paise=tasks.get((TaskKind.TRANSFER, TaskStatus.FAILED), 0),
            taken_back_paise=-ledger.get(LedgerKind.TRANSFER_REVERSAL, 0),
            refunded_paise=-ledger.get(LedgerKind.REFUND, 0),
        )
        return StorePayoutsOut(
            summary=summary,
            items=items,
            next_cursor=page[-1].id if len(transfers) > limit else None,
        )
