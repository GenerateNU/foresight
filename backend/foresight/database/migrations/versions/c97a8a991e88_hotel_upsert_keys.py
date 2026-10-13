"""hotel upsert keys

Gives hotels, room_types and daily_performance the named conflict targets
repository/hotel.py already upserts against; without them every one of its
three functions raises. daily_performance only needs the rename, since its
unique constraint was created unnamed and Postgres generated the name.

Revision ID: c97a8a991e88
Revises: b9719be9df40
Create Date: 2026-10-12 21:42:11.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c97a8a991e88'
down_revision: Union[str, None] = 'b9719be9df40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GENERATED_PERF_KEY = 'daily_performance_room_type_id_stay_date_key'


def upgrade() -> None:
    op.create_unique_constraint('uq_hotels_name_city', 'hotels', ['name', 'city'])
    op.create_unique_constraint(
        'uq_room_types_hotel_name', 'room_types', ['hotel_id', 'name']
    )
    # A rename, not a drop and recreate, so the table is never without its
    # unique and the existing index is reused.
    op.execute(
        f'ALTER TABLE daily_performance RENAME CONSTRAINT '
        f'{_GENERATED_PERF_KEY} TO uq_daily_performance_room_type_stay'
    )


def downgrade() -> None:
    op.execute(
        f'ALTER TABLE daily_performance RENAME CONSTRAINT '
        f'uq_daily_performance_room_type_stay TO {_GENERATED_PERF_KEY}'
    )
    op.drop_constraint('uq_room_types_hotel_name', 'room_types', type_='unique')
    op.drop_constraint('uq_hotels_name_city', 'hotels', type_='unique')
