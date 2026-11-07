"""drop flights and competitor rates

Flights and competitor rates were never loaded: no job filled either table, and
the model's flight inputs were always empty. This drops both tables and the
city airport codes only they used. A downgrade recreates them empty; the
airport codes don't come back.

Revision ID: 53a9a680016f
Revises: fb812a501b3d
Create Date: 2026-11-07 12:48:42.500750

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '53a9a680016f'
down_revision: Union[str, None] = 'fb812a501b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('flight_arrivals')
    op.drop_table('competitor_rates')
    op.drop_column('cities', 'airport_iata')
    op.drop_column('cities', 'airport_icao')


def downgrade() -> None:
    op.add_column('cities', sa.Column('airport_icao', sa.VARCHAR(length=4), autoincrement=False, nullable=True))
    op.add_column('cities', sa.Column('airport_iata', sa.VARCHAR(length=3), autoincrement=False, nullable=True))
    op.create_table('competitor_rates',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('hotel_name', sa.VARCHAR(length=200), autoincrement=False, nullable=False),
    sa.Column('stay_date', sa.DATE(), autoincrement=False, nullable=False),
    sa.Column('rate', sa.NUMERIC(precision=10, scale=2), autoincrement=False, nullable=True),
    sa.Column('is_sold_out', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('source', sa.VARCHAR(length=40), autoincrement=False, nullable=False),
    sa.Column('captured_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('city_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['city_id'], ['cities.id'], name=op.f('fk_competitor_rates_city_id_cities'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_competitor_rates')),
    sa.UniqueConstraint('city_id', 'hotel_name', 'stay_date', 'source', name=op.f('uq_competitor_rates_city_id_hotel_name_stay_date_source'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_table('flight_arrivals',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('airport', sa.VARCHAR(length=10), autoincrement=False, nullable=False),
    sa.Column('arrival_date', sa.DATE(), autoincrement=False, nullable=False),
    sa.Column('flight_count', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('avg_fare_eur', sa.NUMERIC(precision=10, scale=2), autoincrement=False, nullable=True),
    sa.Column('source', sa.VARCHAR(length=40), autoincrement=False, nullable=False),
    sa.Column('captured_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('city_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['city_id'], ['cities.id'], name=op.f('fk_flight_arrivals_city_id_cities'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_flight_arrivals')),
    sa.UniqueConstraint('city_id', 'arrival_date', 'source', name=op.f('uq_flight_arrivals_city_id_arrival_date_source'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
