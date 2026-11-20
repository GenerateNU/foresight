"""tune-up points to its base

A tune-up's artifact now holds only its correction; the base it corrects is
stored once, as its own version, and `pricing_models.base_model_id` points to
it (decision 0078). Before this, every tune-up stored a full copy of its base,
so a daily tune-up duplicated the same base every day. RESTRICT: a base can't
be deleted while a tune-up points to it.

Existing tune-ups get the column from `metrics.base_model_id`, where they kept
the link. Their artifacts still hold a full copy of the base, which loads the
same way, so they keep serving.

A downgrade moves the link back into `metrics` and drops the column. The old
code can't serve a correction-only artifact, so any active tune-up saved after
this revision hands the hotel back to its base.

Revision ID: a7c3e91f4b20
Revises: c3d8f1a2b4e6
Create Date: 2026-11-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91f4b20'
down_revision: Union[str, None] = 'c3d8f1a2b4e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'pricing_models', sa.Column('base_model_id', sa.Integer(), nullable=True)
    )
    op.create_index(
        op.f('ix_pricing_models_base_model_id'), 'pricing_models', ['base_model_id']
    )
    op.create_foreign_key(
        op.f('fk_pricing_models_base_model_id_pricing_models'),
        'pricing_models',
        'pricing_models',
        ['base_model_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.execute(
        """
        UPDATE pricing_models AS tuned
        SET base_model_id = (tuned.metrics ->> 'base_model_id')::int
        WHERE tuned.metrics ? 'base_model_id'
          AND EXISTS (
            SELECT 1 FROM pricing_models AS base
            WHERE base.id = (tuned.metrics ->> 'base_model_id')::int
          )
        """
    )


def downgrade() -> None:
    # Saved after this revision (no link in metrics): correction-only, so an
    # active one gives way to its base. Deactivate first: one active per hotel.
    op.execute(
        """
        CREATE TEMP TABLE _handback ON COMMIT DROP AS
        SELECT id, base_model_id FROM pricing_models
        WHERE base_model_id IS NOT NULL AND is_active
          AND NOT metrics ? 'base_model_id'
        """
    )
    op.execute(
        "UPDATE pricing_models SET is_active = false "
        "WHERE id IN (SELECT id FROM _handback)"
    )
    op.execute(
        "UPDATE pricing_models SET is_active = true "
        "WHERE id IN (SELECT base_model_id FROM _handback)"
    )
    op.execute(
        """
        UPDATE pricing_models
        SET metrics = metrics || jsonb_build_object('base_model_id', base_model_id)
        WHERE base_model_id IS NOT NULL
        """
    )
    op.drop_constraint(
        op.f('fk_pricing_models_base_model_id_pricing_models'),
        'pricing_models',
        type_='foreignkey',
    )
    op.drop_index(op.f('ix_pricing_models_base_model_id'), table_name='pricing_models')
    op.drop_column('pricing_models', 'base_model_id')
