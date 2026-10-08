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
    session_hours: int = 8
    aws_profile: str | None = (
        None  # credentials come from this AWS CLI profile, never from .env keys
    )
    aws_region: str = "us-east-1"
    bedrock_model_id: str = ""  # an inference profile ID such as us.anthropic.claude-haiku-4-5-...
    storage_dir: str = "backend/var/uploads"  # relative paths are resolved from the repo root
    cookie_secure: bool = False  # set COOKIE_SECURE=true when served over https

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
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        return path if path.is_absolute() else ROOT / path

    @property
    def database_url(self) -> URL:
        return self._url(self.postgres_db)

    @property
    def test_database_url(self) -> URL:
        return self._url(self.postgres_test_db)


@lru_cache
def get_settings() -> Settings:
    return Settings()
