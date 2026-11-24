"""Imports every module's ORM models so Alembic autogenerate sees all tables."""

from mallt.core import kv_models
from mallt.core.db import Base
from mallt.modules.audit import models as audit_models
from mallt.modules.catalog import models as catalog_models
from mallt.modules.iam import models as iam_models
from mallt.modules.notify import models as notify_models
from mallt.modules.offers import models as offers_models
from mallt.modules.orders import models as orders_models
from mallt.modules.payments import models as payments_models
from mallt.modules.platform import models as platform_models
from mallt.modules.printing import models as printing_models
from mallt.modules.tenancy import models as tenancy_models

__all__ = [
    "Base",
    "audit_models",
    "catalog_models",
    "iam_models",
    "kv_models",
    "notify_models",
    "offers_models",
    "orders_models",
    "payments_models",
    "platform_models",
    "printing_models",
    "tenancy_models",
]
