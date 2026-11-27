"""drop retired tables

Drops the three tables nothing reads any more, with their rows:
`daily_performance` (Actual & Forecast, decision 0080), `weather` (0081) and
`booking_cancellations` (0091). The first two had been kept until the team
decided; it decided to delete all three (decision 0091). `migrations/env.py`
no longer ignores them as retired tables.

A downgrade recreates the three tables empty, as they were before this
revision. The rows are gone; re-uploading the reports would refill
`booking_cancellations` and `daily_performance` with the old code.

Revision ID: b6d2e8f4a1c9
Revises: a9e3f5c7d1b2
Create Date: 2026-11-26 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6d2e8f4a1c9'
down_revision: Union[str, None] = 'a9e3f5c7d1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        op.f('ix_booking_cancellations_book_ref'), table_name='booking_cancellations'
    )
    op.drop_table('booking_cancellations')
    op.drop_table('weather')
    op.drop_table('daily_performance')


def downgrade() -> None:
    op.create_table(
        'daily_performance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_type_id', sa.Integer(), nullable=False),
        sa.Column('stay_date', sa.Date(), nullable=False),
        sa.Column('rate', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('rooms_available', sa.Integer(), nullable=False),
        sa.Column('rooms_sold', sa.Integer(), nullable=False),
        sa.Column('room_revenue', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('rooms_blocked', sa.Integer(), nullable=True),
        sa.Column('rooms_out_of_service', sa.Integer(), nullable=True),
        sa.Column('waitlist', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['room_type_id'],
            ['room_types.id'],
            name=op.f('fk_daily_performance_room_type_id_room_types'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_daily_performance')),
        sa.UniqueConstraint(
            'room_type_id',
            'stay_date',
            name=op.f('uq_daily_performance_room_type_id_stay_date'),
        ),
    )
    op.create_table(
        'weather',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('city_id', sa.Integer(), nullable=False),
        sa.Column('weather_date', sa.Date(), nullable=False),
        sa.Column('temp_max_c', sa.Float(), nullable=True),
        sa.Column('temp_min_c', sa.Float(), nullable=True),
        sa.Column('precip_mm', sa.Float(), nullable=True),
        sa.Column('wind_kph', sa.Float(), nullable=True),
        sa.Column('condition', sa.String(length=60), nullable=True),
        sa.Column('is_forecast', sa.Boolean(), nullable=False),
        sa.Column('source', sa.String(length=40), nullable=False),
        sa.Column(
            'captured_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['city_id'],
            ['cities.id'],
            name=op.f('fk_weather_city_id_cities'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_weather')),
        sa.UniqueConstraint(
            'city_id',
            'weather_date',
            'is_forecast',
            'source',
            name=op.f('uq_weather_city_id_weather_date_is_forecast_source'),
        ),
    )
    op.create_table(
        'booking_cancellations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('hotel_id', sa.Integer(), nullable=False),
        sa.Column('cancel_ref', sa.String(length=32), nullable=False),
        sa.Column('book_ref', sa.String(length=32), nullable=False),
        sa.Column('booked_at', sa.DateTime(), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(), nullable=False),
        sa.Column('reason_code', sa.String(length=32), nullable=True),
        sa.Column('arrival', sa.Date(), nullable=False),
        sa.Column('departure', sa.Date(), nullable=False),
        sa.Column('lost_revenue', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ['hotel_id'],
            ['hotels.id'],
            name=op.f('fk_booking_cancellations_hotel_id_hotels'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_cancellations')),
        sa.UniqueConstraint(
            'hotel_id',
            'cancel_ref',
            name=op.f('uq_booking_cancellations_hotel_id_cancel_ref'),
        ),
    )
    op.create_index(
        op.f('ix_booking_cancellations_book_ref'),
        'booking_cancellations',
        ['book_ref'],
        unique=False,
    )
