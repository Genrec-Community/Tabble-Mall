from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from mallt.core.config import Settings, get_settings
from mallt.core.errors import install_error_handlers
from mallt.core.logging import RequestIdMiddleware, configure_logging
from mallt.modules.health.router import router as health_router


def _operation_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}_{route.name}"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.env != "test":
        configure_logging()
    app = FastAPI(
        title="MallT API",
        version="0.1.0",
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings
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
    return app
