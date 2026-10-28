"""iam tenancy audit

Revision ID: 0002
Revises: 0001
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Premade roles, as literal data (not imported from the app) so this migration stays
# reproducible. tests/test_migrations.py fails if this drifts from core/rbac.py.
ROLES = [
    (
        "platform_admin",
        "Platform Admin",
        "platform",
        [
            "audit.read",
            "org.billing.manage",
            "org.mall.manage",
            "org.settings.update",
            "org.staff.manage",
            "org.store.manage",
            "platform.kyc.approve",
            "platform.org.manage",
            "store.kyc.submit",
            "store.order.cancel",
            "store.order.read",
            "store.order.update",
            "store.order.verify_pickup",
            "store.product.read",
            "store.product.write",
            "store.profile.update",
            "store.report.read",
            "store.staff.manage",
            "store.stock.update",
            "store.theme.update",
        ],
    ),
    (
        "org_owner",
        "Org Owner",
        "organization",
        [
            "audit.read",
            "org.billing.manage",
            "org.mall.manage",
            "org.settings.update",
            "org.staff.manage",
            "org.store.manage",
            "store.kyc.submit",
            "store.order.cancel",
            "store.order.read",
            "store.order.update",
            "store.order.verify_pickup",
            "store.product.read",
            "store.product.write",
            "store.profile.update",
            "store.report.read",
            "store.staff.manage",
            "store.stock.update",
            "store.theme.update",
        ],
    ),
    (
        "org_manager",
        "Org Manager",
        "organization",
        [
            "org.mall.manage",
            "org.staff.manage",
            "org.store.manage",
            "store.order.cancel",
            "store.order.read",
            "store.order.update",
            "store.order.verify_pickup",
            "store.product.read",
            "store.product.write",
            "store.profile.update",
            "store.report.read",
            "store.staff.manage",
            "store.stock.update",
            "store.theme.update",
        ],
    ),
    (
        "store_owner",
        "Store Owner",
        "store",
        [
            "store.kyc.submit",
            "store.order.cancel",
            "store.order.read",
            "store.order.update",
            "store.order.verify_pickup",
            "store.product.read",
            "store.product.write",
            "store.profile.update",
            "store.report.read",
            "store.staff.manage",
            "store.stock.update",
            "store.theme.update",
        ],
    ),
    (
        "store_staff",
        "Store Staff",
        "store",
        [
            "store.order.read",
            "store.order.update",
            "store.order.verify_pickup",
            "store.product.read",
            "store.stock.update",
        ],
    ),
]


def _role_id(key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"mallt.role.{key}")


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum(
                "staff",
                "customer",
                "system",
                name="audit_actor_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("mall_id", sa.Uuid(), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_org_created",
        "audit_logs",
        ["organization_id", sa.literal_column("created_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_table(
        "customers",
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("google_sub", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "suspended",
                name="customer_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("google_sub", name=op.f("uq_customers_google_sub")),
        sa.UniqueConstraint("phone", name=op.f("uq_customers_phone")),
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "suspended",
                name="org_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("commission_bps", sa.Integer(), server_default="500", nullable=False),
        sa.Column("accept_timeout_s", sa.Integer(), server_default="300", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "identity_type",
            sa.Enum(
                "staff",
                "customer",
                name="identity_kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_tokens_subject_id"), "refresh_tokens", ["subject_id"], unique=False
    )
    op.create_table(
        "roles",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "scope_type",
            sa.Enum(
                "platform",
                "organization",
                "mall",
                "store",
                name="role_scope_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("key", name=op.f("uq_roles_key")),
    )
    op.create_table(
        "staff_users",
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "suspended",
                name="staff_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("must_change_password", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("totp_secret", sa.Text(), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_users")),
        sa.UniqueConstraint("username", name=op.f("uq_staff_users_username")),
    )
    op.create_table(
        "malls",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "suspended",
                name="mall_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_malls_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_malls")),
        sa.UniqueConstraint("slug", name=op.f("uq_malls_slug")),
    )
    op.create_index(op.f("ix_malls_organization_id"), "malls", ["organization_id"], unique=False)
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_role_permissions_role_id_roles")
        ),
        sa.PrimaryKeyConstraint("role_id", "permission", name="pk_role_permissions"),
    )
    op.create_table(
        "stores",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("mall_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "suspended",
                name="store_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("commission_bps", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["mall_id"], ["malls.id"], name=op.f("fk_stores_mall_id_malls")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_stores_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("mall_id", "slug", name="uq_stores_mall_id_slug"),
    )
    op.create_index(op.f("ix_stores_mall_id"), "stores", ["mall_id"], unique=False)
    op.create_index(op.f("ix_stores_organization_id"), "stores", ["organization_id"], unique=False)
    op.create_table(
        "role_assignments",
        sa.Column("staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope_type",
            sa.Enum(
                "platform",
                "organization",
                "mall",
                "store",
                name="assignment_scope_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("mall_id", sa.Uuid(), nullable=True),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["staff_users.id"],
            name=op.f("fk_role_assignments_granted_by_staff_users"),
        ),
        sa.ForeignKeyConstraint(
            ["mall_id"], ["malls.id"], name=op.f("fk_role_assignments_mall_id_malls")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_role_assignments_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_role_assignments_role_id_roles")
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["staff_users.id"],
            name=op.f("fk_role_assignments_staff_user_id_staff_users"),
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], name=op.f("fk_role_assignments_store_id_stores")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_assignments")),
        sa.UniqueConstraint(
            "staff_user_id",
            "role_id",
            "scope_type",
            "organization_id",
            "mall_id",
            "store_id",
            name="uq_role_assignments_grant",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("ix_role_assignments_organization_id"),
        "role_assignments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_role_assignments_staff_user_id"),
        "role_assignments",
        ["staff_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_role_assignments_store_id"), "role_assignments", ["store_id"], unique=False
    )

    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("scope_type", sa.Text()),
        sa.column("is_system", sa.Boolean()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid()),
        sa.column("permission", sa.Text()),
    )
    op.bulk_insert(
        roles,
        [
            {"id": _role_id(k), "key": k, "name": n, "scope_type": st, "is_system": True}
            for k, n, st, _ in ROLES
        ],
    )
    op.bulk_insert(
        role_permissions,
        [{"role_id": _role_id(k), "permission": p} for k, _, _, perms in ROLES for p in perms],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_role_assignments_store_id"), table_name="role_assignments")
    op.drop_index(op.f("ix_role_assignments_staff_user_id"), table_name="role_assignments")
    op.drop_index(op.f("ix_role_assignments_organization_id"), table_name="role_assignments")
    op.drop_table("role_assignments")
    op.drop_index(op.f("ix_stores_organization_id"), table_name="stores")
    op.drop_index(op.f("ix_stores_mall_id"), table_name="stores")
    op.drop_table("stores")
    op.drop_table("role_permissions")
    op.drop_index(op.f("ix_malls_organization_id"), table_name="malls")
    op.drop_table("malls")
    op.drop_table("staff_users")
    op.drop_table("roles")
    op.drop_index(op.f("ix_refresh_tokens_subject_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("organizations")
    op.drop_table("customers")
    op.drop_index("ix_audit_logs_org_created", table_name="audit_logs")
    op.drop_table("audit_logs")
