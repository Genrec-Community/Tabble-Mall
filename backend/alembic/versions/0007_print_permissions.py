"""print permissions on the premade roles

Revision ID: 0007
Revises: 0006
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _role_id(key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"mallt.role.{key}")


# role -> permissions added by this migration (literal data, like 0002)
ADDED = {
    "platform_admin": ["store.printer.manage", "store.order.print"],
    "org_owner": ["store.printer.manage", "store.order.print"],
    "org_manager": ["store.printer.manage", "store.order.print"],
    "store_owner": ["store.printer.manage", "store.order.print"],
    "store_staff": ["store.order.print"],
}


def upgrade() -> None:
    table = sa.table(
        "role_permissions", sa.column("role_id", sa.Uuid()), sa.column("permission", sa.Text())
    )
    op.bulk_insert(
        table,
        [{"role_id": _role_id(k), "permission": p} for k, perms in ADDED.items() for p in perms],
    )


def downgrade() -> None:
    for key, perms in ADDED.items():
        for permission in perms:
            op.execute(
                sa.text(
                    "DELETE FROM role_permissions WHERE role_id = :r AND permission = :p"
                ).bindparams(r=_role_id(key), p=permission)
            )
