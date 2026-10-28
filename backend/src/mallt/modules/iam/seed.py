from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.enums import ActorType
from mallt.core.rbac import Scope
from mallt.core.security import new_totp_secret, totp_uri
from mallt.modules.audit.service import Actor, AuditService
from mallt.modules.iam.users import IamUsers


async def seed_admin(
    session: AsyncSession, *, username: str, display_name: str, password: str
) -> str:
    """Create a Platform Admin with TOTP already enabled. Returns the otpauth URI (shown once)."""
    users = IamUsers(session)
    staff = await users.create_staff_user(
        username=username,
        display_name=display_name,
        email=None,
        password=password,
        must_change_password=False,
    )
    secret = new_totp_secret()
    staff.totp_secret = secret
    staff.totp_enabled = True
    await users.assign_role(staff.id, "platform_admin", Scope.platform(), granted_by=None)
    await AuditService(session).record(
        actor=Actor(ActorType.SYSTEM, None),
        action="staff.seeded",
        target_type="staff_user",
        target_id=staff.id,
        scope=Scope.platform(),
        after={"username": staff.username, "role": "platform_admin"},
    )
    return totp_uri(secret, staff.username)
