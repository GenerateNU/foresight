"""Declarative base shared by every model."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Every constraint and index gets a deterministic name derived from its table
# and columns, so migrations can drop or rename it and repositories can target
# it in ON CONFLICT without relying on names Postgres generated.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
