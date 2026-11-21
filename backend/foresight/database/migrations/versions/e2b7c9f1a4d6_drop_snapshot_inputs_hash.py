"""drop snapshot inputs_hash

A snapshot was matched to a night's new inputs by a SHA-256 of the model id and
its inputs (`inputs_hash`, decision 0038). It's now matched by comparing the
model id and the stored `inputs` directly (decision 0084), so the hash column
goes.

A downgrade adds it back as an empty string, as the migration that first added
it did. An empty hash never matches, so the older code prices that night again
and saves a new snapshot; no history is lost.

Revision ID: e2b7c9f1a4d6
Revises: d8f4a6c2e715
Create Date: 2026-11-20 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7c9f1a4d6'
down_revision: Union[str, None] = 'd8f4a6c2e715'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('recommendation_snapshots', 'inputs_hash')


def downgrade() -> None:
    op.add_column(
        'recommendation_snapshots',
        sa.Column('inputs_hash', sa.String(length=64), nullable=False, server_default=''),
    )
    op.alter_column('recommendation_snapshots', 'inputs_hash', server_default=None)
