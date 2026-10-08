from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Read from the process environment, falling back to the root .env file.

    Ports and credentials have no defaults on purpose: .env is the only place they live.
    """

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_host: str = "localhost"
    postgres_port: int
    postgres_db: str
    postgres_test_db: str

    jwt_secret: str = ""

    # Demo logins for `make seed`. No defaults here on purpose: they live in .env only.
    demo_coordinator_password: str | None = None
    demo_admin_password: str | None = None
    demo_pantry_manager_password: str | None = None

    log_level: str = "INFO"

    def _url(self, database: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=database,
        )

    @property
    def database_url(self) -> URL:
        return self._url(self.postgres_db)

    @property
    def test_database_url(self) -> URL:
        return self._url(self.postgres_test_db)


@lru_cache
def get_settings() -> Settings:
    return Settings()
