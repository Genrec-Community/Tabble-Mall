from enum import StrEnum


class PayoutStatus(StrEnum):
    PENDING = "pending"  # submitted, the provider is verifying
    ACTIVE = "active"  # transfers enabled: the store can take orders
    DISABLED = "disabled"  # rejected or switched off by the provider


class TaskKind(StrEnum):
    TRANSFER = "transfer"  # store's share to its payout account
    REVERSAL = "reversal"  # take a transfer back before refunding
    REFUND = "refund"  # money back to the customer


class TaskStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"  # gave up; needs a person
    CANCELLED = "cancelled"  # no longer needed (e.g. a transfer that never ran)


class LedgerKind(StrEnum):
    CHARGE = "charge"
    COMMISSION = "commission"
    TRANSFER = "transfer"
    TRANSFER_REVERSAL = "transfer_reversal"
    REFUND = "refund"
