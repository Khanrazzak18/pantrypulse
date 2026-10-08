from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.api import health
from app.config import Settings, get_settings
from app.db import make_engine
from app.errors import register_exception_handlers
from app.logging import configure_logging
from app.middleware import register_request_middleware


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
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
    return app
