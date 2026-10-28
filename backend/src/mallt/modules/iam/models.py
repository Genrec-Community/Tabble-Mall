import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, PrimaryKeyConstraint, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mallt.core.db import Base, IdMixin, TimestampMixin
from mallt.core.enums import ActiveStatus, IdentityKind, text_enum
from mallt.core.rbac import ScopeType


class StaffUser(IdMixin, TimestampMixin, Base):
    __tablename__ = "staff_users"

    username: Mapped[str] = mapped_column(Text, unique=True)  # lowercase, globally unique
    display_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[ActiveStatus] = mapped_column(
        text_enum(ActiveStatus, "staff_status"), default=ActiveStatus.ACTIVE
    )
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Customer(IdMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    phone: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ActiveStatus] = mapped_column(
        text_enum(ActiveStatus, "customer_status"), default=ActiveStatus.ACTIVE
    )


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    scope_type: Mapped[ScopeType] = mapped_column(text_enum(ScopeType, "role_scope_type"))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (PrimaryKeyConstraint("role_id", "permission", name="pk_role_permissions"),)

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    permission: Mapped[str] = mapped_column(Text)


class RoleAssignment(IdMixin, TimestampMixin, Base):
    __tablename__ = "role_assignments"
    __table_args__ = (
        UniqueConstraint(
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

    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("staff_users.id"), index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    scope_type: Mapped[ScopeType] = mapped_column(text_enum(ScopeType, "assignment_scope_type"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    mall_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("malls.id"), nullable=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stores.id"), nullable=True, index=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id"), nullable=True
    )


class RefreshToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    identity_type: Mapped[IdentityKind] = mapped_column(text_enum(IdentityKind, "identity_kind"))
    subject_id: Mapped[uuid.UUID] = mapped_column(index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "Customer",
    "RefreshToken",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "StaffUser",
]
