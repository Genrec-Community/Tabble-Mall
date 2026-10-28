"""index the remaining foreign keys on role_assignments

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(op.f("ix_role_assignments_role_id"), "role_assignments", ["role_id"])
    op.create_index(op.f("ix_role_assignments_mall_id"), "role_assignments", ["mall_id"])
    op.create_index(op.f("ix_role_assignments_granted_by"), "role_assignments", ["granted_by"])


def downgrade() -> None:
    op.drop_index(op.f("ix_role_assignments_granted_by"), table_name="role_assignments")
    op.drop_index(op.f("ix_role_assignments_mall_id"), table_name="role_assignments")
    op.drop_index(op.f("ix_role_assignments_role_id"), table_name="role_assignments")
