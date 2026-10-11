from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.ai.llm_provider import BedrockProvider, LLMProvider
from app.api import (
    admin,
    allocations,
    auth,
    dashboard,
    donations,
    donors,
    forecasts,
    health,
    pantries,
    pantry_portal,
)
from app.config import Settings, get_settings
from app.db import make_engine
from app.errors import register_exception_handlers
from app.logging import configure_logging
from app.middleware import register_request_middleware
from app.security.http import register_origin_check, register_security_headers
from app.services.forecasting import ForecastConfig
from app.storage import LocalStorage, StorageBackend

MIN_JWT_SECRET_LENGTH = 32


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    llm: LLMProvider | None = None,
    storage: StorageBackend | None = None,
    forecast_config: ForecastConfig | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if len(settings.jwt_secret) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET must be set in .env and be at least {MIN_JWT_SECRET_LENGTH} characters "
            "long. Generate one with: openssl rand -hex 32"
        )
    configure_logging(settings.log_level)
    engine = engine or make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        engine.dispose()

    docs = "/docs" if settings.expose_api_docs else None
    app = FastAPI(
        title="PantryPulse API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs,
        redoc_url="/redoc" if settings.expose_api_docs else None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    # The running app always uses real Bedrock; tests pass a scripted fake instead.
    app.state.llm = llm or BedrockProvider(settings)
    app.state.storage = storage or LocalStorage(settings.storage_path)
    app.state.forecast_config = forecast_config or ForecastConfig()
    app.state.today = date.today  # tests pin this to a fixed day
    register_exception_handlers(app)
    register_origin_check(app, settings)
    register_request_middleware(app)
    register_security_headers(app, settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(pantries.router)
    app.include_router(donations.router)
    app.include_router(donors.router)
    app.include_router(forecasts.router)
    app.include_router(allocations.router)
    app.include_router(pantry_portal.router)
    app.include_router(dashboard.router)
    app.include_router(admin.router)
    return app
