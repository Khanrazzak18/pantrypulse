from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.tokens import create_token, decode_token

SECRET = "x" * 64
NOW = datetime.now(UTC)


def forged(payload: dict, secret: str = SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(payload, secret, algorithm=algorithm)


def valid_payload(**overrides) -> dict:
    base = {"sub": "7", "iat": NOW, "exp": NOW + timedelta(hours=1)}
    return {**base, **overrides}


def test_token_round_trips_to_the_user_id():
    assert decode_token(create_token(7, SECRET, 8), SECRET) == 7


def test_token_carries_only_the_user_id_and_timestamps():
    payload = jwt.decode(create_token(7, SECRET, 8), SECRET, algorithms=["HS256"])
    assert set(payload) == {"sub", "iat", "exp"}


def test_token_lifetime_matches_the_requested_hours():
    payload = jwt.decode(create_token(7, SECRET, 8), SECRET, algorithms=["HS256"])
    assert payload["exp"] - payload["iat"] == 8 * 3600


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(forged(valid_payload(exp=NOW - timedelta(seconds=5))), id="expired"),
        pytest.param(forged(valid_payload(), secret="y" * 40), id="wrong secret"),
        pytest.param(forged(valid_payload(), algorithm="HS512"), id="different algorithm"),
        pytest.param(
            jwt.encode(valid_payload(), key="", algorithm="none"), id="alg none (unsigned)"
        ),
        pytest.param(forged({"sub": "7", "iat": NOW}), id="no expiry"),
        pytest.param(forged({"iat": NOW, "exp": NOW + timedelta(hours=1)}), id="no subject"),
        pytest.param(forged(valid_payload(sub="not-a-number")), id="non-numeric subject"),
        pytest.param("garbage", id="not a jwt"),
        pytest.param("", id="empty"),
    ],
)
def test_bad_tokens_are_rejected(token):
    assert decode_token(token, SECRET) is None


def test_a_tampered_payload_is_rejected():
    header, _, signature = create_token(7, SECRET, 8).split(".")
    other = create_token(8, SECRET, 8).split(".")[1]
    assert decode_token(f"{header}.{other}.{signature}", SECRET) is None
