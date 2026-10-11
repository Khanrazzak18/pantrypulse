"""One error envelope for the whole API: {"error": {"code", "message", "details"}}."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import request_id_var

logger = logging.getLogger("pantrypulse.errors")

# Errors raised by the database driver when it cannot be reached or has dropped the connection.
OUTAGE = (OperationalError, InterfaceError)

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """The one error shape: {"error": {"code", "message", "details", "request_id"}}. The request id
    is also the X-Request-ID header and is in every log line, so a user can quote it."""
    error = {
        "code": code,
        "message": message,
        "details": details,
        "request_id": request_id_var.get(),
    }
    return JSONResponse(status_code=status_code, content={"error": error}, headers=headers)


UNAVAILABLE = "The service is temporarily unavailable. Please try again in a moment."


def unavailable_response() -> JSONResponse:
    return error_response(503, "service_unavailable", UNAVAILABLE, None, {"Retry-After": "5"})


def internal_response() -> JSONResponse:
    return error_response(500, "internal_error", "Something went wrong.")


async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return error_response(exc.status_code, code, message)


_PATH_RANGE_TYPES = {"greater_than_equal", "less_than_equal", "greater_than", "less_than"}


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    # An id in the URL outside the range the database can hold names a record that cannot exist.
    if any(e["loc"][0] == "path" and e["type"] in _PATH_RANGE_TYPES for e in errors):
        return error_response(404, "not_found", "Not found.")
    details = [
        {
            "field": ".".join(str(part) for part in err["loc"][1:]),
            "message": err["msg"].removeprefix("Value error, "),
            "type": err["type"],
        }
        for err in errors
    ]
    return error_response(422, "validation_error", "Some fields are invalid.", details)


async def _outage_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("database_unavailable", exc_info=exc)
    return unavailable_response()


async def _data_error_handler(_: Request, exc: DataError) -> JSONResponse:
    # The database refused a value (out of range, unstorable text). It is the caller's input.
    logger.warning("database_rejected_value", exc_info=exc)
    return error_response(422, "validation_error", "Some fields are invalid.", [])


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    for error_type in OUTAGE:
        app.add_exception_handler(error_type, _outage_handler)
    app.add_exception_handler(DataError, _data_error_handler)
