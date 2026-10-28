"""Permissions, scopes and the premade (system) roles. Pure: no I/O.

The matrix mirrors spec §5.2. Migration 0002 seeds the same data as literals, and a test
fails if the two ever drift apart.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum


class ScopeType(StrEnum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    MALL = "mall"
    STORE = "store"


_DEPTH = {
    ScopeType.PLATFORM: 0,
    ScopeType.ORGANIZATION: 1,
    ScopeType.MALL: 2,
    ScopeType.STORE: 3,
}


class P(StrEnum):
    PLATFORM_ORG_MANAGE = "platform.org.manage"
    PLATFORM_KYC_APPROVE = "platform.kyc.approve"
    ORG_SETTINGS_UPDATE = "org.settings.update"
    ORG_BILLING_MANAGE = "org.billing.manage"
    ORG_MALL_MANAGE = "org.mall.manage"
    ORG_STORE_MANAGE = "org.store.manage"
    ORG_STAFF_MANAGE = "org.staff.manage"
    STORE_PROFILE_UPDATE = "store.profile.update"
    STORE_THEME_UPDATE = "store.theme.update"
    STORE_PRODUCT_WRITE = "store.product.write"
    STORE_PRODUCT_READ = "store.product.read"
    STORE_STOCK_UPDATE = "store.stock.update"
    STORE_ORDER_READ = "store.order.read"
    STORE_ORDER_UPDATE = "store.order.update"
    STORE_ORDER_VERIFY_PICKUP = "store.order.verify_pickup"
    STORE_ORDER_CANCEL = "store.order.cancel"
    STORE_KYC_SUBMIT = "store.kyc.submit"
    STORE_STAFF_MANAGE = "store.staff.manage"
    STORE_REPORT_READ = "store.report.read"
    AUDIT_READ = "audit.read"


@dataclass(frozen=True)
class Scope:
    type: ScopeType
    organization_id: uuid.UUID | None = None
    mall_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        depth = _DEPTH[self.type]
        ids = (self.organization_id, self.mall_id, self.store_id)
        for level, value in enumerate(ids, start=1):
            if (level <= depth) != (value is not None):
                raise ValueError(f"{self.type} scope has an incomplete or extra id chain")

    @classmethod
    def platform(cls) -> "Scope":
        return cls(ScopeType.PLATFORM)

    @classmethod
    def org(cls, organization_id: uuid.UUID) -> "Scope":
        return cls(ScopeType.ORGANIZATION, organization_id)

    @classmethod
    def mall(cls, organization_id: uuid.UUID, mall_id: uuid.UUID) -> "Scope":
        return cls(ScopeType.MALL, organization_id, mall_id)

    @classmethod
    def store(cls, organization_id: uuid.UUID, mall_id: uuid.UUID, store_id: uuid.UUID) -> "Scope":
        return cls(ScopeType.STORE, organization_id, mall_id, store_id)


def contains(outer: Scope, inner: Scope) -> bool:
    """True if ``outer`` is the same scope as ``inner`` or an ancestor of it."""
    depth = _DEPTH[outer.type]
    if depth > _DEPTH[inner.type]:
        return False
    outer_ids = (outer.organization_id, outer.mall_id, outer.store_id)[:depth]
    inner_ids = (inner.organization_id, inner.mall_id, inner.store_id)[:depth]
    return outer_ids == inner_ids


@dataclass(frozen=True)
class RoleDef:
    key: str
    name: str
    scope_type: ScopeType
    permissions: frozenset[P]


_STORE_STAFF = frozenset(
    {
        P.STORE_PRODUCT_READ,
        P.STORE_STOCK_UPDATE,
        P.STORE_ORDER_READ,
        P.STORE_ORDER_UPDATE,
        P.STORE_ORDER_VERIFY_PICKUP,
    }
)
_STORE_OWNER = _STORE_STAFF | {
    P.STORE_PROFILE_UPDATE,
    P.STORE_THEME_UPDATE,
    P.STORE_PRODUCT_WRITE,
    P.STORE_ORDER_CANCEL,
    P.STORE_KYC_SUBMIT,
    P.STORE_STAFF_MANAGE,
    P.STORE_REPORT_READ,
}
_ORG_MANAGER = (_STORE_OWNER - {P.STORE_KYC_SUBMIT}) | {
    P.ORG_MALL_MANAGE,
    P.ORG_STORE_MANAGE,
    P.ORG_STAFF_MANAGE,
}
_ORG_OWNER = _ORG_MANAGER | {
    P.STORE_KYC_SUBMIT,
    P.ORG_SETTINGS_UPDATE,
    P.ORG_BILLING_MANAGE,
    P.AUDIT_READ,
}

SYSTEM_ROLES: dict[str, RoleDef] = {
    r.key: r
    for r in (
        RoleDef("platform_admin", "Platform Admin", ScopeType.PLATFORM, frozenset(P)),
        RoleDef("org_owner", "Org Owner", ScopeType.ORGANIZATION, frozenset(_ORG_OWNER)),
        RoleDef("org_manager", "Org Manager", ScopeType.ORGANIZATION, frozenset(_ORG_MANAGER)),
        RoleDef("store_owner", "Store Owner", ScopeType.STORE, frozenset(_STORE_OWNER)),
        RoleDef("store_staff", "Store Staff", ScopeType.STORE, _STORE_STAFF),
    )
}

# The permission that lets someone manage staff at a given scope type (anti-escalation rule).
STAFF_MANAGE_FOR: dict[ScopeType, P] = {
    ScopeType.PLATFORM: P.PLATFORM_ORG_MANAGE,
    ScopeType.ORGANIZATION: P.ORG_STAFF_MANAGE,
    ScopeType.MALL: P.ORG_STAFF_MANAGE,
    ScopeType.STORE: P.STORE_STAFF_MANAGE,
}

# Who may hand out each role: the granter must hold one of these roles at a scope containing the
# target. This is on top of "hold every permission in the role", which alone would let an Org
# Manager mint more Org Managers (they already hold all of that role's permissions).
GRANT_RULES: dict[str, frozenset[str]] = {
    "platform_admin": frozenset({"platform_admin"}),
    "org_owner": frozenset({"platform_admin", "org_owner"}),
    "org_manager": frozenset({"platform_admin", "org_owner"}),
    # Not org_manager: store owners can submit KYC (bank details), which managers cannot.
    "store_owner": frozenset({"platform_admin", "org_owner", "store_owner"}),
    "store_staff": frozenset({"platform_admin", "org_owner", "org_manager", "store_owner"}),
}
