import asyncio

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from mallt.core.rbac import SYSTEM_ROLES
from tests.dbtools import TEST_DATABASE_URL, alembic_config, ensure_database, with_database

EXPECTED_TABLES = {
    "organizations",
    "malls",
    "stores",
    "staff_users",
    "customers",
    "roles",
    "role_permissions",
    "role_assignments",
    "refresh_tokens",
    "audit_logs",
    "kv_store",
}


async def test_upgrade_downgrade_roundtrip() -> None:
    url = with_database(TEST_DATABASE_URL, "mallt_migration_test")
    await ensure_database(url)
    conn = await asyncpg.connect(url.replace("+asyncpg", ""))
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        cfg = alembic_config(url)
        await asyncio.to_thread(command.upgrade, cfg, "head")
        tables = {
            r["tablename"]
            for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        assert EXPECTED_TABLES <= tables
        await asyncio.to_thread(command.downgrade, cfg, "base")
        left = {
            r["tablename"]
            for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        }
        assert left <= {"alembic_version"}
        await asyncio.to_thread(command.upgrade, cfg, "head")
    finally:
        await conn.close()


async def test_seeded_roles_match_code(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        roles = (
            await conn.execute(text("SELECT id, key, name, scope_type, is_system FROM roles"))
        ).all()
        perms = (await conn.execute(text("SELECT role_id, permission FROM role_permissions"))).all()
    assert {r.key for r in roles} == set(SYSTEM_ROLES)
    for r in roles:
        code = SYSTEM_ROLES[r.key]
        assert (r.name, r.scope_type, r.is_system) == (code.name, code.scope_type.value, True)
        assert {p.permission for p in perms if p.role_id == r.id} == {
            p.value for p in code.permissions
        }


async def test_models_match_migrations() -> None:
    """`alembic check` raises if the ORM models and the migrations have drifted apart."""
    await asyncio.to_thread(command.check, alembic_config(TEST_DATABASE_URL))
