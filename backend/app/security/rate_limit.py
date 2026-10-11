"""Rate limits kept in the database (so every API instance shares them), per user and per endpoint.

One row per user and scope holds a counter for a fixed one-hour window. Every request to a limited
endpoint counts, whatever it returns, because even a failing upload or AI call can cost money. A
limit of N means the (N+1)th request in the window gets a 429. The limits come from .env.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db
from app.errors import ApiError
from app.models import User

WINDOW_SECONDS = 3600

SCOPE_SETTING = {
    "uploads": "rate_limit_uploads_per_hour",
    "weekly_refresh": "rate_limit_refresh_per_hour",
}  # every other scope uses rate_limit_ai_per_hour

# One statement: start a new window if the old one is over, otherwise add one; return where we are.
COUNT_SQL = text(
    """
    INSERT INTO rate_limits (key_hash, window_start, count)
    VALUES (:key, now(), 1)
    ON CONFLICT (key_hash) DO UPDATE SET
        count = CASE WHEN rate_limits.window_start <= now() - make_interval(secs => :window)
                     THEN 1 ELSE rate_limits.count + 1 END,
        window_start = CASE WHEN rate_limits.window_start <= now() - make_interval(secs => :window)
                            THEN now() ELSE rate_limits.window_start END
    RETURNING count, GREATEST(1, CEIL(EXTRACT(EPOCH FROM
        (window_start + make_interval(secs => :window) - now()))))::int AS retry_after
    """
)


def limit_for(settings, scope: str) -> int:
    return getattr(settings, SCOPE_SETTING.get(scope, "rate_limit_ai_per_hour"))


def count_request(db: Session, user_id: int, scope: str, limit: int) -> None:
    key = hashlib.sha256(f"rate:{scope}:{user_id}".encode()).hexdigest()
    count, retry_after = db.execute(COUNT_SQL, {"key": key, "window": WINDOW_SECONDS}).one()
    db.commit()
    if count > limit:
        minutes = max(1, math.ceil(retry_after / 60))
        raise ApiError(
            429,
            "rate_limited",
            f"You've reached the hourly limit for this action. Try again in {minutes} "
            f"minute{'s' if minutes != 1 else ''}.",
            {"scope": scope, "limit_per_hour": limit, "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(scope: str, role_check: Callable[..., User]) -> Callable[..., None]:
    """A dependency: the right role first (a wrong role is a 403, not counted), then the limit."""

    def dependency(
        request: Request, user: User = Depends(role_check), db: Session = Depends(get_db)
    ) -> None:
        count_request(db, user.id, scope, limit_for(request.app.state.settings, scope))

    return dependency
