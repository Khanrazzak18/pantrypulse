from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine


def make_engine(url: URL | str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
