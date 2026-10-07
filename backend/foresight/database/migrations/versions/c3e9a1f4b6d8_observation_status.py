"""observation status

Each sighting keeps the status its source reported, so a deleted duplicate
listing can be told apart from the live listing it shares an event with.
Existing PredictHQ sightings are backfilled from their payload.

Revision ID: c3e9a1f4b6d8
Revises: b7d41e0c9a52
Create Date: 2026-10-06 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e9a1f4b6d8'
down_revision: Union[str, None] = 'b7d41e0c9a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'event_observations', sa.Column('status', sa.String(length=20), nullable=True)
    )
    op.execute(
        """
        UPDATE event_observations SET status = CASE payload->>'state'
            WHEN 'active' THEN 'ACTIVE'
            WHEN 'predicted' THEN 'PROVISIONAL'
            WHEN 'deleted' THEN 'DELETED'
        END
        WHERE source = 'PREDICTHQ'
        """
    )


def downgrade() -> None:
    op.drop_column('event_observations', 'status')
