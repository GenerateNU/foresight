"""hotel timezone

Stay nights are local to the hotel. OpenSky reports arrivals as UTC instants,
so counting them per night needs the hotel's IANA zone. Nullable: existing
hotels have none until it is set, and sources that need it refuse to run.

Revision ID: a7c3e8d2f4b6
Revises: f2c8d5a1e9b3
Create Date: 2026-10-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e8d2f4b6'
down_revision: Union[str, None] = 'f2c8d5a1e9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hotels', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('hotels', 'timezone')
