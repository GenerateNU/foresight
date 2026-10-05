"""canonical events and observations

Replaces the placeholder `events` table with the canonical event contract plus
an append-only `event_observations` staging table. Nothing writes to `events`
yet, so it is dropped rather than migrated.

Revision ID: b7d41e0c9a52
Revises: 72e850f4fa7b
Create Date: 2026-10-05 11:12:04.882341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7d41e0c9a52'
down_revision: Union[str, None] = '72e850f4fa7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('events')
    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dedupe_key', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('title_norm', sa.String(length=300), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('venue', sa.String(length=200), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=False),
    sa.Column('city_slug', sa.String(length=120), nullable=False),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('start_local_date', sa.Date(), nullable=False),
    sa.Column('end_local_date', sa.Date(), nullable=False),
    sa.Column('start_at_utc', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_at_utc', sa.DateTime(timezone=True), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('date_precision', sa.String(length=20), nullable=False),
    sa.Column('expected_attendance', sa.Integer(), nullable=True),
    sa.Column('impact_rank', sa.Integer(), nullable=True),
    sa.Column('local_rank', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('url', sa.String(length=600), nullable=True),
    sa.Column('primary_source', sa.String(length=40), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )
    op.create_index(op.f('ix_events_title_norm'), 'events', ['title_norm'], unique=False)
    op.create_index('ix_events_city_slug_start', 'events', ['city_slug', 'start_local_date'], unique=False)
    op.create_table('event_observations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('source_ref', sa.String(length=600), nullable=False),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'source_ref')
    )


def downgrade() -> None:
    op.drop_table('event_observations')
    op.drop_index('ix_events_city_slug_start', table_name='events')
    op.drop_index(op.f('ix_events_title_norm'), table_name='events')
    op.drop_table('events')
    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('venue', sa.String(length=200), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('expected_attendance', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
