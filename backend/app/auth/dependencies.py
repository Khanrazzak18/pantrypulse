from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.tokens import decode_session
from app.errors import ApiError
from app.models import User

COOKIE_NAME = "pp_session"
# Admins can do everything a coordinator can (see the role table in CLAUDE.md).
COORDINATOR_ACCESS = ("coordinator", "admin")


def get_db(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The logged-in, active user, or a 401. Looked up fresh on every request."""
    not_authenticated = ApiError(401, "not_authenticated", "Please log in to continue.")
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise not_authenticated
    claims = decode_session(token, request.app.state.settings.jwt_secret)
    if claims is None:
        raise not_authenticated
    user = db.get(User, claims.user_id)
    # A token is good only for the version the user is on now: logout, deactivation and role or
    # password changes all raise it.
    if user is None or not user.is_active or user.token_version != claims.version:
        raise not_authenticated
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise ApiError(403, "forbidden", "You do not have access to this.")
        return user

    return dependency


require_coordinator = require_roles(*COORDINATOR_ACCESS)
require_admin = require_roles("admin")
