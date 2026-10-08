import logging

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ApiError
from app.schemas.health import HealthResponse

logger = logging.getLogger("pantrypulse.health")
router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("health_db_check_failed")
        raise ApiError(503, "database_unavailable", "Database is not reachable.") from None
    return HealthResponse(status="ok", database="ok")
