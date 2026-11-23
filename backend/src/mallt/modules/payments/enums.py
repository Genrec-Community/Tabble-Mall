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
    GATEWAY_FEE = "gateway_fee"  # borne by the store, deducted from its transfer
    # A fee a store still owes (+, e.g. after a refund) or that was held back from a later
    # transfer to settle it (-). The sum per store is what it owes now.
    FEE_OWED = "fee_owed"
    TRANSFER = "transfer"
    TRANSFER_REVERSAL = "transfer_reversal"
    REFUND = "refund"
