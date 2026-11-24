"""Label money tasks with the store's order number, for the payouts and admin screens.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payment_tasks", sa.Column("order_label", sa.Text(), nullable=True))
    # The store payouts screen lists a store's tasks newest first.
    op.create_index("ix_payment_tasks_store_id_id", "payment_tasks", ["store_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_payment_tasks_store_id_id", table_name="payment_tasks")
    op.drop_column("payment_tasks", "order_label")
