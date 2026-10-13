"""hotel airport codes

Revision ID: e5a9c3b2d7f1
Revises: d4f8e2a7b1c9
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a9c3b2d7f1'
down_revision: Union[str, None] = 'd4f8e2a7b1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hotels', sa.Column('airport_iata', sa.String(length=3), nullable=True))
    op.add_column('hotels', sa.Column('airport_icao', sa.String(length=4), nullable=True))


def downgrade() -> None:
    op.drop_column('hotels', 'airport_icao')
    op.drop_column('hotels', 'airport_iata')
