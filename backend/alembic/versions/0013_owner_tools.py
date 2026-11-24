"""Owner tools: feature switches, featured spots, and "sold out for today" on products.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_features",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_platform_features")),
    )
    op.create_table(
        "featured_spots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("mall_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_featured_spots_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["mall_id"], ["malls.id"], name=op.f("fk_featured_spots_mall_id_malls")
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], name=op.f("fk_featured_spots_store_id_stores")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_featured_spots")),
    )
    op.create_index(
        op.f("ix_featured_spots_organization_id"), "featured_spots", ["organization_id"]
    )
    op.create_index(op.f("ix_featured_spots_mall_id"), "featured_spots", ["mall_id"])
    op.create_index(op.f("ix_featured_spots_store_id"), "featured_spots", ["store_id"])
    op.add_column(
        "products", sa.Column("sold_out_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("products", "sold_out_until")
    op.drop_index(op.f("ix_featured_spots_store_id"), table_name="featured_spots")
    op.drop_index(op.f("ix_featured_spots_mall_id"), table_name="featured_spots")
    op.drop_index(op.f("ix_featured_spots_organization_id"), table_name="featured_spots")
    op.drop_table("featured_spots")
    op.drop_table("platform_features")
