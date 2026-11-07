"""file job kinds and drop base_rate

One job kind per uploaded Guestline report: PERFORMANCE becomes ACTUAL_FORECAST,
and RESERVATIONS and CANCELLATIONS are new. `jobs.kind` and `jobs.status` are
VARCHARs without a CHECK, so the new kinds and the CANCELLED status need no
schema change; existing PERFORMANCE rows are renamed so they still load. A
downgrade renames them back and deletes rows the old code can't load
(the two new kinds, and cancelled jobs).

`room_types.base_rate` is dropped: nothing reads it (decision 0053). A
downgrade adds it back nullable, because the old values are gone.

Revision ID: 9a4c2e7b1d35
Revises: 0e44b8374dd5
Create Date: 2026-11-07 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a4c2e7b1d35'
down_revision: Union[str, None] = '0e44b8374dd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE jobs SET kind = 'ACTUAL_FORECAST' WHERE kind = 'PERFORMANCE'")
    op.drop_column('room_types', 'base_rate')


def downgrade() -> None:
    op.add_column(
        'room_types',
        sa.Column('base_rate', sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.execute("DELETE FROM jobs WHERE kind IN ('RESERVATIONS', 'CANCELLATIONS')")
    op.execute("DELETE FROM jobs WHERE status = 'CANCELLED'")
    op.execute("UPDATE jobs SET kind = 'PERFORMANCE' WHERE kind = 'ACTUAL_FORECAST'")
