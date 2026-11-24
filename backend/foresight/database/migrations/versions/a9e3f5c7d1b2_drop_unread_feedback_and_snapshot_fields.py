"""drop unread feedback and snapshot fields

Nothing reads these, and each can be worked out from what's kept (decision
0086):

- `pricing_model_feedback`: which manager rates each version learnt from. The
  feedback table holds every rate with its time, and a version holds its
  training window, so the link adds nothing.
- `feedback.verdict`: the manager's rate against the snapshot's rate.
- `feedback.timing`: the stay date against when the feedback was given.
- `recommendation_snapshots.model_version`: the version of `model_id`.

A downgrade recreates them. The table comes back empty. Each column is filled
from what it was derived from: the verdict from the feedback's and snapshot's
rates (about right when either is missing), the timing from the stay date and
`created_at` in UTC, and the version from the snapshot's model.

Revision ID: a9e3f5c7d1b2
Revises: f4c1d8a2b6e3
Create Date: 2026-11-24 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9e3f5c7d1b2'
down_revision: Union[str, None] = 'f4c1d8a2b6e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        op.f('ix_pricing_model_feedback_feedback_id'),
        table_name='pricing_model_feedback',
    )
    op.drop_table('pricing_model_feedback')
    op.drop_column('feedback', 'verdict')
    op.drop_column('feedback', 'timing')
    op.drop_column('recommendation_snapshots', 'model_version')


def downgrade() -> None:
    op.add_column(
        'recommendation_snapshots',
        sa.Column('model_version', sa.String(length=60), nullable=True),
    )
    op.execute(
        """
        UPDATE recommendation_snapshots AS s
        SET model_version = m.algorithm || '-v' || m.version
        FROM pricing_models AS m
        WHERE m.id = s.model_id
        """
    )
    op.alter_column('recommendation_snapshots', 'model_version', nullable=False)

    op.add_column('feedback', sa.Column('verdict', sa.String(length=20), nullable=True))
    op.add_column('feedback', sa.Column('timing', sa.String(length=10), nullable=True))
    op.execute(
        """
        UPDATE feedback AS f
        SET verdict = CASE
                WHEN f.rate > s.rate THEN 'TOO_LOW'
                WHEN f.rate < s.rate THEN 'TOO_HIGH'
                ELSE 'ABOUT_RIGHT'
            END
        FROM recommendation_snapshots AS s
        WHERE s.id = f.snapshot_id
        """
    )
    op.execute("UPDATE feedback SET verdict = 'ABOUT_RIGHT' WHERE verdict IS NULL")
    op.execute(
        """
        UPDATE feedback
        SET timing = CASE
            WHEN stay_date < (created_at AT TIME ZONE 'UTC')::date THEN 'AFTER'
            ELSE 'BEFORE'
        END
        """
    )
    op.alter_column('feedback', 'verdict', nullable=False)
    op.alter_column('feedback', 'timing', nullable=False)

    op.create_table(
        'pricing_model_feedback',
        sa.Column('pricing_model_id', sa.Integer(), nullable=False),
        sa.Column('feedback_id', sa.Integer(), nullable=False),
        sa.Column('training_rate', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ['feedback_id'],
            ['feedback.id'],
            name=op.f('fk_pricing_model_feedback_feedback_id_feedback'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['pricing_model_id'],
            ['pricing_models.id'],
            name=op.f('fk_pricing_model_feedback_pricing_model_id_pricing_models'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'pricing_model_id', 'feedback_id', name=op.f('pk_pricing_model_feedback')
        ),
    )
    op.create_index(
        op.f('ix_pricing_model_feedback_feedback_id'),
        'pricing_model_feedback',
        ['feedback_id'],
        unique=False,
    )
