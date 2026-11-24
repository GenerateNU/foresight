"""drop snapshot interval

Recommendations no longer carry an 80% range (decision 0085): the served model
trains once on every row, so nothing is held out to calibrate one. The
snapshot's `interval_low`, `interval_high` and `interval_level` go.

A downgrade adds them back with every existing row's range set to its own rate
(a zero-width interval) at level 0.8, because the old ranges are gone.

Revision ID: f4c1d8a2b6e3
Revises: e2b7c9f1a4d6
Create Date: 2026-11-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4c1d8a2b6e3'
down_revision: Union[str, None] = 'e2b7c9f1a4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'recommendation_snapshots'


def upgrade() -> None:
    for column in ('interval_low', 'interval_high', 'interval_level'):
        op.drop_column(_TABLE, column)


def downgrade() -> None:
    for column in ('interval_low', 'interval_high'):
        op.add_column(_TABLE, sa.Column(column, sa.Numeric(10, 2), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column(
            'interval_level', sa.Float(), nullable=False, server_default=sa.text('0.8')
        ),
    )
    op.execute(f"UPDATE {_TABLE} SET interval_low = rate, interval_high = rate")
    for column in ('interval_low', 'interval_high'):
        op.alter_column(_TABLE, column, nullable=False)
    op.alter_column(_TABLE, 'interval_level', server_default=None)
