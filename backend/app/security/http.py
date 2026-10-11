"""HTTP protections for the API: security headers on every response and a CSRF check.

CSRF: the session cookie is SameSite=Lax, which already stops most cross-site posts. On top of that,
any request that changes data and carries browser headers must come from our own site: its Origin
must be one we allow, and Sec-Fetch-Site (sent by every current browser) must not say cross-site or
same-site. Requests with neither header are not browsers (curl, scripts, the test suite) and pass:
they cannot be tricked into sending a victim's cookie.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings
from app.errors import error_response

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_JSON_BYTES = 1_000_000  # no JSON request needs more
MAX_UPLOAD_REQUEST_BYTES = 11 * 1024 * 1024  # a 10 MB file plus the form around it
HSTS = "max-age=31536000; includeSubDomains"
# An API only ever returns JSON: it needs no scripts, frames, camera or anything else.
API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}


TOO_LARGE = "That request is too large. Uploads are limited to 10 MB."


def body_limit(method: str, path: str) -> int:
    is_upload = path == "/api/donations" and method == "POST"
    return MAX_UPLOAD_REQUEST_BYTES if is_upload else MAX_JSON_BYTES


class BodyLimit:
    """Counts request bytes as they arrive and stops at the limit, whatever Content-Length says
    (or whether it was sent at all, as with a chunked body). A pure ASGI middleware sitting just
    outside the router, so every reader of the body is counted and the request id is already set.

    FastAPI turns any exception raised while it reads the body into its own 400, so this does not
    raise. When the limit is crossed it sends the 413 itself, tells the reader the client went
    away, and drops whatever the application tries to send afterwards."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            return await self.app(scope, receive, send)
        limit = body_limit(scope["method"], scope["path"])
        total = 0
        refused = False

        async def limited():
            nonlocal total, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    refused = True
                    response = error_response(413, "payload_too_large", TOO_LARGE)
                    await response(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            if not refused:
                await send(message)

        try:
            await self.app(scope, limited, guarded_send)
        except Exception:
            if not refused:  # after a 413 the application's own failure is expected and moot
                raise


def register_body_limit(app: FastAPI) -> None:
    """Add first, so it sits just outside the router and inside the request-id middleware."""
    app.add_middleware(BodyLimit)


def allowed_origins(settings: Settings) -> set[str]:
    extra = {o.strip().rstrip("/") for o in settings.allowed_origins.split(",") if o.strip()}
    if extra:
        return extra
    port = settings.web_port
    return {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}


def register_origin_check(app: FastAPI, settings: Settings) -> None:
    """Add before the request-context middleware, so a refusal still carries a request id."""
    origins = allowed_origins(settings)

    class OriginCheck(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            declared = request.headers.get("content-length", "")
            if declared.isdigit():  # refuse an oversized body from its declared size, unread
                if int(declared) > body_limit(request.method, request.url.path):
                    return error_response(413, "payload_too_large", TOO_LARGE)
            if request.method not in SAFE_METHODS:
                origin = request.headers.get("origin")
                site = request.headers.get("sec-fetch-site")
                bad_origin = origin is not None and origin.rstrip("/") not in origins
                bad_site = site is not None and site not in ("same-origin", "none")
                if bad_origin or bad_site:
                    return error_response(
                        403,
                        "forbidden_origin",
                        "This request was blocked because it came from another site.",
                    )
            return await call_next(request)

    app.add_middleware(OriginCheck)


def register_security_headers(app: FastAPI, settings: Settings) -> None:
    """Add after the request-context middleware, so the headers wrap every response."""

    class Headers(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            for name, value in API_HEADERS.items():
                response.headers.setdefault(name, value)
            if settings.cookie_secure:  # only when the site really is served over https
                response.headers.setdefault("Strict-Transport-Security", HSTS)
            return response

    app.add_middleware(Headers)
