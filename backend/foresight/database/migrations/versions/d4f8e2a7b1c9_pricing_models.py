"""pricing models

Revision ID: d4f8e2a7b1c9
Revises: c97a8a991e88
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4f8e2a7b1c9'
down_revision: Union[str, None] = 'c97a8a991e88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pricing_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hotel_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('algorithm', sa.String(length=60), nullable=False),
        sa.Column('artifact', sa.LargeBinary(), nullable=False),
        sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            'lib_versions', postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column('data_start', sa.Date(), nullable=False),
        sa.Column('data_end', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column(
            'trained_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['hotel_id'], ['hotels.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hotel_id', 'version'),
    )
    op.create_index(
        op.f('ix_pricing_models_hotel_id'), 'pricing_models', ['hotel_id']
    )
    op.create_index(
        'uq_pricing_models_active_per_hotel',
        'pricing_models',
        ['hotel_id'],
        unique=True,
        postgresql_where=sa.text('is_active'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_pricing_models_active_per_hotel',
        table_name='pricing_models',
        postgresql_where=sa.text('is_active'),
    )
    op.drop_index(op.f('ix_pricing_models_hotel_id'), table_name='pricing_models')
    op.drop_table('pricing_models')
