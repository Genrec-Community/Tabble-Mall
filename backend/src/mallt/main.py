from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import async_sessionmaker

from mallt.core.config import Settings, get_settings
from mallt.core.db import make_engine
from mallt.core.errors import install_error_handlers
from mallt.core.kv import make_kv
from mallt.core.logging import RequestIdMiddleware, configure_logging
from mallt.core.storage import Storage
from mallt.modules.audit.router import router as audit_router
from mallt.modules.catalog.router import public_router as catalog_public_router
from mallt.modules.catalog.router import router as catalog_router
from mallt.modules.health.router import router as health_router
from mallt.modules.iam.customer_router import customer_router
from mallt.modules.iam.google import make_google_verifier
from mallt.modules.iam.router import staff_router
from mallt.modules.iam.sms import make_sms_sender
from mallt.modules.staff.router import router as staff_mgmt_router
from mallt.modules.tenancy.router import routers as tenancy_routers


def _operation_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}_{route.name}"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.env != "test":
        configure_logging()
    engine = make_engine(settings.database_url)
    kv = make_kv(settings, engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await kv.aclose()
        await engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title="MallT API",
        version="0.1.0",
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.kv = kv
    app.state.storage = Storage(settings)
    app.state.sms = make_sms_sender(settings)
    app.state.google = make_google_verifier(settings)
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(staff_router)
    app.include_router(customer_router)
    for router in tenancy_routers:
        app.include_router(router)
    app.include_router(staff_mgmt_router)
    app.include_router(catalog_router)
    app.include_router(catalog_public_router)
    app.include_router(audit_router)
    return app
