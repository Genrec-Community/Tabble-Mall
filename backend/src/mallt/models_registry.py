"""Imports every module's ORM models so Alembic autogenerate sees all tables."""

from mallt.core import kv_models
from mallt.core.db import Base
from mallt.modules.audit import models as audit_models
from mallt.modules.iam import models as iam_models
from mallt.modules.tenancy import models as tenancy_models

__all__ = ["Base", "audit_models", "iam_models", "kv_models", "tenancy_models"]
