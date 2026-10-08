from collections.abc import Iterable

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Predictable constraint names make migrations and error messages readable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def in_list(column: str, values: Iterable[str]) -> str:
    """SQL for a CHECK that a text column holds one of a fixed set of values."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


MONDAY_CHECK = "extract(isodow from {col}) = 1"
