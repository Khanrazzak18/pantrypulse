"""Login lockout. Five failed attempts for one email, or 20 from one address, within 15 minutes
lock that email or address for 15 minutes. Counts are in the database (see `LoginThrottle`).

Unknown emails are counted exactly like known ones, so the lock does not reveal which accounts
exist. A locked email refuses even the right password until the lock ends.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import LoginThrottle

WINDOW = timedelta(minutes=15)
LOCK = timedelta(minutes=15)
LIMITS = {"email": 5, "ip": 20}


def _hash(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def seconds_locked(db: Session, keys: list[tuple[str, str]]) -> int:
    """Seconds until the last lock on any of these keys ends, or 0 if none is locked."""
    now = _now()
    hashes = [_hash(kind, value) for kind, value in keys]
    until = db.scalars(
        select(LoginThrottle.locked_until).where(
            LoginThrottle.key_hash.in_(hashes), LoginThrottle.locked_until > now
        )
    ).all()
    return max((math.ceil((u - now).total_seconds()) for u in until), default=0)


def record_failure(db: Session, keys: list[tuple[str, str]]) -> None:
    now = _now()
    for kind, value in keys:
        key = _hash(kind, value)
        db.execute(
            insert(LoginThrottle)
            .values(key_hash=key, failures=0, first_failure_at=now)
            .on_conflict_do_nothing(index_elements=["key_hash"])
        )
        row = db.scalar(
            select(LoginThrottle)
            .where(LoginThrottle.key_hash == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        expired_lock = row.locked_until is not None and row.locked_until <= now
        if expired_lock or now - row.first_failure_at > WINDOW:
            row.failures, row.first_failure_at, row.locked_until = 0, now, None
        row.failures += 1
        if row.failures >= LIMITS[kind]:
            row.locked_until = now + LOCK
    db.commit()


def clear(db: Session, kind: str, value: str) -> None:
    row = db.get(LoginThrottle, _hash(kind, value))
    if row is not None:
        db.delete(row)
        db.commit()
