import pytest

from mallt.core.ids import uuid7
from mallt.core.rbac import (
    GRANT_RULES,
    STAFF_MANAGE_FOR,
    SYSTEM_ROLES,
    P,
    Scope,
    ScopeType,
    contains,
)

R = SYSTEM_ROLES


def test_role_keys_and_scope_types() -> None:
    assert {k: r.scope_type for k, r in R.items()} == {
        "platform_admin": ScopeType.PLATFORM,
        "org_owner": ScopeType.ORGANIZATION,
        "org_manager": ScopeType.ORGANIZATION,
        "store_owner": ScopeType.STORE,
        "store_staff": ScopeType.STORE,
    }


def test_matrix_matches_spec() -> None:
    assert R["platform_admin"].permissions == set(P)
    assert R["store_staff"].permissions == {
        P.STORE_PRODUCT_READ,
        P.STORE_STOCK_UPDATE,
        P.STORE_ORDER_READ,
        P.STORE_ORDER_UPDATE,
        P.STORE_ORDER_VERIFY_PICKUP,
    }
    assert R["store_owner"].permissions == R["store_staff"].permissions | {
        P.STORE_PROFILE_UPDATE,
        P.STORE_THEME_UPDATE,
        P.STORE_PRODUCT_WRITE,
        P.STORE_ORDER_CANCEL,
        P.STORE_KYC_SUBMIT,
        P.STORE_STAFF_MANAGE,
        P.STORE_REPORT_READ,
    }
    assert R["org_manager"].permissions == R["store_owner"].permissions - {P.STORE_KYC_SUBMIT} | {
        P.ORG_MALL_MANAGE,
        P.ORG_STORE_MANAGE,
        P.ORG_STAFF_MANAGE,
    }
    assert R["org_owner"].permissions == R["org_manager"].permissions | {
        P.STORE_KYC_SUBMIT,
        P.ORG_SETTINGS_UPDATE,
        P.ORG_BILLING_MANAGE,
        P.AUDIT_READ,
    }


def test_billing_kyc_and_audit_boundaries() -> None:
    assert P.ORG_BILLING_MANAGE not in R["org_manager"].permissions
    assert P.STORE_KYC_SUBMIT not in R["org_manager"].permissions
    assert P.AUDIT_READ not in R["store_owner"].permissions
    assert P.PLATFORM_ORG_MANAGE not in R["org_owner"].permissions
    assert P.PLATFORM_KYC_APPROVE not in R["org_owner"].permissions


def test_permission_values_are_dotted_strings() -> None:
    assert P.STORE_ORDER_VERIFY_PICKUP == "store.order.verify_pickup"
    assert P.PLATFORM_ORG_MANAGE == "platform.org.manage"


def test_staff_manage_permission_per_scope() -> None:
    assert STAFF_MANAGE_FOR == {
        ScopeType.PLATFORM: P.PLATFORM_ORG_MANAGE,
        ScopeType.ORGANIZATION: P.ORG_STAFF_MANAGE,
        ScopeType.MALL: P.ORG_STAFF_MANAGE,
        ScopeType.STORE: P.STORE_STAFF_MANAGE,
    }


def test_contains() -> None:
    o1, o2, m, s = uuid7(), uuid7(), uuid7(), uuid7()
    assert contains(Scope.platform(), Scope.store(o1, m, s))
    assert contains(Scope.platform(), Scope.platform())
    assert contains(Scope.org(o1), Scope.store(o1, m, s))
    assert contains(Scope.org(o1), Scope.org(o1))
    assert contains(Scope.mall(o1, m), Scope.store(o1, m, s))
    assert not contains(Scope.org(o2), Scope.store(o1, m, s))
    assert not contains(Scope.store(o1, m, s), Scope.org(o1))
    assert not contains(Scope.store(o1, m, s), Scope.store(o1, m, uuid7()))
    assert not contains(Scope.mall(o1, m), Scope.store(o1, uuid7(), s))
    assert not contains(Scope.org(o1), Scope.platform())


def test_incomplete_chain_rejected() -> None:
    with pytest.raises(ValueError):
        Scope(ScopeType.STORE, organization_id=uuid7())
    with pytest.raises(ValueError):
        Scope(ScopeType.PLATFORM, organization_id=uuid7())
    with pytest.raises(ValueError):
        Scope(ScopeType.ORGANIZATION)


def test_grant_rules_say_who_may_hand_out_each_role() -> None:
    assert set(GRANT_RULES) == set(SYSTEM_ROLES)
    assert all("platform_admin" in granters for granters in GRANT_RULES.values())
    # The spec: an Org Manager can't create Org Owners or Org Managers; an owner can.
    assert "org_manager" not in GRANT_RULES["org_owner"]
    assert "org_manager" not in GRANT_RULES["org_manager"]
    assert "org_owner" in GRANT_RULES["org_owner"] and "org_owner" in GRANT_RULES["org_manager"]
    # Org managers and store owners may build store teams; store staff may not.
    assert {"org_manager", "store_owner"} <= GRANT_RULES["store_staff"]
    assert "store_staff" not in GRANT_RULES["store_staff"]
    # Store owners can submit KYC (bank details) and managers cannot, so managers cannot mint them;
    # listing them as granters would only mislead the API and the UI.
    assert "org_manager" not in GRANT_RULES["store_owner"]
