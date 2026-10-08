import pytest

from app.main import create_app


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_app_refuses_to_start_without_a_strong_jwt_secret(settings, engine, secret):
    weak = settings.model_copy(update={"jwt_secret": secret})
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(weak, engine)


def test_app_starts_with_a_32_character_secret(settings, engine):
    create_app(settings.model_copy(update={"jwt_secret": "x" * 32}), engine)
