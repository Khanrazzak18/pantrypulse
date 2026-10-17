from app.config import Settings


def test_database_urls_are_built_from_env_parts(settings: Settings):
    url = settings.database_url
    test_url = settings.test_database_url
    assert url.drivername == "postgresql+psycopg"
    assert url.database == settings.postgres_db
    assert test_url.database == settings.postgres_test_db
    assert url.port == settings.postgres_port == test_url.port
    assert settings.postgres_db != settings.postgres_test_db


def test_ssl_mode_is_added_to_the_database_url_only_when_set(settings: Settings):
    assert "sslmode" not in settings.database_url.query
    secured = settings.model_copy(update={"postgres_sslmode": "require"})
    assert secured.database_url.query["sslmode"] == "require"
    assert secured.test_database_url.query["sslmode"] == "require"


def test_the_password_is_never_part_of_the_rendered_url(settings: Settings):
    assert settings.postgres_password not in settings.database_url.render_as_string()


def test_aws_credentials_default_to_the_task_role_not_a_profile(settings: Settings):
    # in AWS no profile is set, so boto3 uses the task role; locally AWS_PROFILE names a CLI profile
    assert settings.model_copy(update={"aws_profile": None}).aws_profile is None
