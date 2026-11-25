from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """Base class for every model.

    Every constraint and index is named from its table and columns
    (`NAMING_CONVENTION`), so migrations can drop or rename it and upserts can
    target it by name.

    Attributes:
        metadata (MetaData): The shared metadata, with the naming convention.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
