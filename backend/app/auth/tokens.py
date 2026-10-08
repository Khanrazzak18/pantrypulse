"""Session tokens: a signed JWT that carries only the user id and timestamps.

The role is deliberately not in the token. It is read from the database on every request, so a
role change or a deactivation takes effect immediately.
"""

from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"


def create_token(user_id: int, secret: str, hours: int, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": issued, "exp": issued + timedelta(hours=hours)}
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> int | None:
    """The user id if the token is valid, otherwise None. Never raises."""
    try:
        # Pinning `algorithms` is what rejects unsigned ("alg": "none") and re-signed tokens.
        payload = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "iat", "sub"]}
        )
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError):
        return None
