import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import COOKIE_NAME, current_user, get_db
from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import create_token
from app.errors import ApiError
from app.models import Pantry, User
from app.schemas.auth import LoginRequest, UserOut

logger = logging.getLogger("pantrypulse.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Verified against when the email is unknown, so unknown and known emails cost the same time.
_DUMMY_HASH = hash_password("a-password-nobody-has")


def user_out(db: Session, user: User) -> UserOut:
    pantry = db.get(Pantry, user.pantry_id) if user.pantry_id else None
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        pantry_id=user.pantry_id,
        pantry_name=pantry.name if pantry else None,
    )


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    settings = request.app.state.settings
    user = db.scalar(select(User).where(User.email == body.email))
    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)

    if user is None:
        reason = "unknown_email"
    elif not password_ok:
        reason = "wrong_password"
    elif not user.is_active:
        reason = "inactive_user"
    else:
        reason = None
    if reason:
        # The reason is logged; the email and password never are. The client sees one message.
        logger.warning("login_failed", extra={"reason": reason})
        raise ApiError(401, "invalid_credentials", "Incorrect email or password.")

    token = create_token(user.id, settings.jwt_secret, settings.session_hours)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    logger.info("login_succeeded", extra={"user_id": user.id})
    return user_out(db, user)


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    settings = request.app.state.settings
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> UserOut:
    return user_out(db, user)
