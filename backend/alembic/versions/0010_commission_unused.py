"""Stop using commission (expand step of its removal).

MallT keeps no money (owner decision, 2026-11-23), so the M3 commission columns are no longer read
or written. This step only relaxes the NOT NULL columns so code without them can insert rows; a
later migration drops organizations.commission_bps, stores.commission_bps,
customer_orders.commission_paise and store_orders.commission_bps / commission_paise once no
deployed code uses them. The ORM keeps them, marked retired, until then.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = [
    ("customer_orders", "commission_paise", sa.BigInteger()),
    ("store_orders", "commission_bps", sa.Integer()),
    ("store_orders", "commission_paise", sa.BigInteger()),
]


def upgrade() -> None:
    for table, column, type_ in _COLUMNS:
        op.alter_column(table, column, existing_type=type_, nullable=True)


def downgrade() -> None:
    for table, column, type_ in _COLUMNS:
        # Constant identifiers from _COLUMNS above, never input.
        op.execute(sa.text(f"UPDATE {table} SET {column} = 0 WHERE {column} IS NULL"))  # noqa: S608
        op.alter_column(table, column, existing_type=type_, nullable=False)
