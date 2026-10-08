from app.config import Settings


def test_database_urls_are_built_from_env_parts(settings: Settings):
    url = settings.database_url
    test_url = settings.test_database_url
    assert url.drivername == "postgresql+psycopg"
    assert url.database == settings.postgres_db
    assert test_url.database == settings.postgres_test_db
    assert url.port == settings.postgres_port == test_url.port
    assert settings.postgres_db != settings.postgres_test_db
