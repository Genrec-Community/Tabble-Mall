from enum import StrEnum

from sqlalchemy import Enum


class ActiveStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class IdentityKind(StrEnum):
    STAFF = "staff"
    CUSTOMER = "customer"


class ActorType(StrEnum):
    STAFF = "staff"
    CUSTOMER = "customer"
    SYSTEM = "system"


def text_enum(enum: type[StrEnum], name: str) -> Enum:
    """Store a StrEnum as checked text (not a Postgres enum type), which is easy to migrate."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )
