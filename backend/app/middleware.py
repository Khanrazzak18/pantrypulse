import logging
import re
import time
import uuid

from fastapi import FastAPI, Request

from app.errors import error_response
from app.logging import request_id_var

logger = logging.getLogger("pantrypulse.request")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def register_request_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Log the real error; the client only ever sees a generic message.
                logger.exception("unhandled_error")
                response = error_response(500, "internal_error", "Something went wrong.")
            route = request.scope.get("route")
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "route": getattr(route, "path", request.url.path),
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            return response
        finally:
            request_id_var.reset(token)
