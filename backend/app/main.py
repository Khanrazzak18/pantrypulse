from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.api import auth, health, pantries
from app.config import Settings, get_settings
from app.db import make_engine
from app.errors import register_exception_handlers
from app.logging import configure_logging
from app.middleware import register_request_middleware

MIN_JWT_SECRET_LENGTH = 32


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
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

    app = FastAPI(title="PantryPulse API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    register_exception_handlers(app)
    register_request_middleware(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(pantries.router)
    return app
