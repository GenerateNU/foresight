"""pricing model description and training summary

Training now runs as a job (the new TRAIN job kind), and every model version
records what it tried (`description`, written by whoever trained it) and what
it was trained on (`training_summary`: nights used and excluded, room types,
which signals had data). Existing rows get no description and an empty
summary.

`jobs.kind` is a VARCHAR without a CHECK, so TRAIN needs no schema change.
A downgrade deletes TRAIN jobs, because the older code can't load them; jobs
are run history, not data.

Revision ID: 4c1e7a9d2b10
Revises: 80bab95951e7
Create Date: 2026-10-15 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4c1e7a9d2b10'
down_revision: Union[str, None] = '80bab95951e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pricing_models', sa.Column('description', sa.Text(), nullable=True))
    op.add_column(
        'pricing_models',
        sa.Column(
            'training_summary',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind = 'TRAIN'")
    op.drop_column('pricing_models', 'training_summary')
    op.drop_column('pricing_models', 'description')
