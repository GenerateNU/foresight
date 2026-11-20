"""drop dead columns

Drops four columns nothing reads (decision 0082):

- `recommendation_snapshots.uncertainty`: the sub-model spread (0006). The
  80% interval is the range shown; the spread wasn't used.
- `pricing_model_feedback.rate_replaced` and `weight_factor`: from 0044, when
  feedback replaced a night's rate or changed its weight. Since 0076 a manager
  rate is a row of its own, so every row had the same values.
- `hotels.total_rooms`: set by hand on create, read by nothing but a label.

A downgrade adds them back with neutral values, because the old ones are gone:
uncertainty 0, rate_replaced true, weight_factor 1, total_rooms 0.

Revision ID: d8f4a6c2e715
Revises: c5e2b8d4a913
Create Date: 2026-11-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8f4a6c2e715'
down_revision: Union[str, None] = 'c5e2b8d4a913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, type, value given to existing rows on downgrade)
_COLUMNS = [
    ('recommendation_snapshots', 'uncertainty', sa.Numeric(10, 2), '0'),
    ('pricing_model_feedback', 'rate_replaced', sa.Boolean(), 'true'),
    ('pricing_model_feedback', 'weight_factor', sa.Numeric(10, 3), '1'),
    ('hotels', 'total_rooms', sa.Integer(), '0'),
]


def upgrade() -> None:
    for table, column, _, _ in _COLUMNS:
        op.drop_column(table, column)


def downgrade() -> None:
    for table, column, type_, value in _COLUMNS:
        op.add_column(
            table,
            sa.Column(column, type_, nullable=False, server_default=sa.text(value)),
        )
        op.alter_column(table, column, server_default=None)
