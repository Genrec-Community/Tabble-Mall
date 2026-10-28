"""kv_store: Postgres fallback for Redis

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kv_store",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("counter", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_kv_store"),
    )
    op.create_index("ix_kv_store_expires_at", "kv_store", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_kv_store_expires_at", table_name="kv_store")
    op.drop_table("kv_store")
