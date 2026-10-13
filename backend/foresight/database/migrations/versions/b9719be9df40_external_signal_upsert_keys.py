"""external signal upsert keys

Gives weather, flight_arrivals and competitor_rates the natural keys their
ingestion needs: without a conflict target every re-run appends duplicate
rows. Source stays in each key, so two providers describing the same day are
distinct rows rather than silently overwriting one another, and a provider
re-fetching a day updates its own row in place.

Revision ID: b9719be9df40
Revises: a1b2c3d4e5f6
Create Date: 2026-10-12 02:26:03.496929

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b9719be9df40'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_weather_city_date_kind_source',
        'weather',
        ['city', 'weather_date', 'is_forecast', 'source'],
    )
    op.create_unique_constraint(
        'uq_flight_arrivals_airport_date_source',
        'flight_arrivals',
        ['airport', 'arrival_date', 'source'],
    )
    op.create_unique_constraint(
        'uq_competitor_rates_hotel_date_source',
        'competitor_rates',
        ['hotel_name', 'city', 'stay_date', 'source'],
    )
    # The unique constraint above leads on hotel_name, so it cannot serve the
    # market-wide read: every competitor's rate across a range of nights.
    op.create_index(
        'ix_competitor_rates_city_stay', 'competitor_rates', ['city', 'stay_date']
    )


def downgrade() -> None:
    op.drop_index('ix_competitor_rates_city_stay', table_name='competitor_rates')
    op.drop_constraint(
        'uq_competitor_rates_hotel_date_source', 'competitor_rates', type_='unique'
    )
    op.drop_constraint(
        'uq_flight_arrivals_airport_date_source', 'flight_arrivals', type_='unique'
    )
    op.drop_constraint('uq_weather_city_date_kind_source', 'weather', type_='unique')
