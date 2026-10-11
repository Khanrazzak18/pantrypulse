from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine


def make_engine(url: URL | str) -> Engine:
    # hide_parameters keeps the values of a failed statement (manifest text, notes) out of error
    # messages, and so out of the logs.
    return create_engine(
        url, pool_pre_ping=True, hide_parameters=True, connect_args={"connect_timeout": 3}
    )
