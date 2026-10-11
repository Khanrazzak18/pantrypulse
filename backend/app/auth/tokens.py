"""Session tokens: a signed JWT that carries the user id, a version number and timestamps.

The role is deliberately not in the token. It is read from the database on every request, so a
role change or a deactivation takes effect immediately. The version number is the user's
`token_version`: logging out, deactivating or changing the user raises it, which makes every token
issued earlier (even a copied one) stop working.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"


@dataclass(frozen=True)
class Claims:
    user_id: int
    version: int


def create_token(
    user_id: int, secret: str, hours: int, now: datetime | None = None, version: int = 0
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "ver": version,
        "iat": issued,
        "exp": issued + timedelta(hours=hours),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_session(token: str, secret: str) -> Claims | None:
    """The user id and version if the token is valid, otherwise None. Never raises."""
    try:
        # Pinning `algorithms` is what rejects unsigned ("alg": "none") and re-signed tokens.
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub", "ver"]},
        )
        version = payload["ver"]
        if isinstance(version, bool) or not isinstance(version, int):
            return None
        return Claims(int(payload["sub"]), version)
    except (jwt.PyJWTError, ValueError, TypeError):
        return None


def decode_token(token: str, secret: str) -> int | None:
    """The user id if the token is valid, otherwise None. Never raises."""
    claims = decode_session(token, secret)
    return claims.user_id if claims else None
