"""performance blocks roos waitlist

Adds group-block rooms, rooms out of service and the waitlist to each night,
from the Actual & Forecast export. All three are nullable: nights already
imported keep working with them empty. A downgrade drops the three columns.


Revision ID: fb812a501b3d
Revises: 6ff80354e16b
Create Date: 2026-11-01 20:37:47.712434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb812a501b3d'
down_revision: Union[str, None] = '6ff80354e16b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('daily_performance', sa.Column('rooms_blocked', sa.Integer(), nullable=True))
    op.add_column('daily_performance', sa.Column('rooms_out_of_service', sa.Integer(), nullable=True))
    op.add_column('daily_performance', sa.Column('waitlist', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_column('daily_performance', 'waitlist')
    op.drop_column('daily_performance', 'rooms_out_of_service')
    op.drop_column('daily_performance', 'rooms_blocked')
    # ### end Alembic commands ###
