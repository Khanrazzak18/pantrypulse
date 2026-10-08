import logging

from sqlalchemy import create_engine, pool

from alembic import context
from app.config import get_settings
from app.models import Base

config = context.config
target_metadata = Base.metadata

if config.attributes.get("url") is None:  # running from the CLI: show what is happening
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def run_migrations_online() -> None:
    # Tests pass the URL in via config.attributes; the CLI uses the app database from .env.
    url = config.attributes.get("url") or get_settings().database_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; run against a database.")
run_migrations_online()
