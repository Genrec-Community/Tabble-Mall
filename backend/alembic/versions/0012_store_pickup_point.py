"""Where a store's customers collect their food (a counter number, a level), shown to customers.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("store_settings", sa.Column("pickup_point", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("store_settings", "pickup_point")
