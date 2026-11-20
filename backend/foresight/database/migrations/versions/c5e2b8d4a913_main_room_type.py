"""main room type

Every model version prices one room type, the main product (decision 0079):
Guestline's DOUBLE room on the room-only rate. `pricing_models.room_type_id`
records it; serving and the tune-up read it instead of the old
`training_summary` JSON, which nothing has written since 0076 and is dropped.
`room_types.room_count` is dropped too: nothing reads it.

Existing versions get no room type. None of them can serve after this change
anyway (they read `room_type` and weather inputs that are no longer built), and
they are to be deleted; serving asks for a new version.

A downgrade drops the column and adds the other two back: `training_summary`
as `{}` and `room_count` as 0, because the old values are gone.

Revision ID: c5e2b8d4a913
Revises: a7c3e91f4b20
Create Date: 2026-11-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5e2b8d4a913'
down_revision: Union[str, None] = 'a7c3e91f4b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'pricing_models', sa.Column('room_type_id', sa.Integer(), nullable=True)
    )
    op.create_index(
        op.f('ix_pricing_models_room_type_id'), 'pricing_models', ['room_type_id']
    )
    op.create_foreign_key(
        op.f('fk_pricing_models_room_type_id_room_types'),
        'pricing_models',
        'room_types',
        ['room_type_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.drop_column('pricing_models', 'training_summary')
    op.drop_column('room_types', 'room_count')


def downgrade() -> None:
    op.add_column(
        'room_types',
        sa.Column('room_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('room_types', 'room_count', server_default=None)
    op.add_column(
        'pricing_models',
        sa.Column(
            'training_summary',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.drop_constraint(
        op.f('fk_pricing_models_room_type_id_room_types'),
        'pricing_models',
        type_='foreignkey',
    )
    op.drop_index(op.f('ix_pricing_models_room_type_id'), table_name='pricing_models')
    op.drop_column('pricing_models', 'room_type_id')
