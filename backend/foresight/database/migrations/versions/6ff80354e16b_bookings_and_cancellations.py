"""bookings and cancellations

Adds two new tables for Guestline's Daily New Reservations and Cancellations
exports. Existing data is untouched. A downgrade drops both tables.

Revision ID: 6ff80354e16b
Revises: b4e8a2c6d19f
Create Date: 2026-11-01 19:20:56.048848

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ff80354e16b'
down_revision: Union[str, None] = 'b4e8a2c6d19f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('booking_cancellations',
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
    sa.ForeignKeyConstraint(['hotel_id'], ['hotels.id'], name=op.f('fk_booking_cancellations_hotel_id_hotels'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_cancellations')),
    sa.UniqueConstraint('hotel_id', 'cancel_ref', name=op.f('uq_booking_cancellations_hotel_id_cancel_ref'))
    )
    op.create_index(op.f('ix_booking_cancellations_book_ref'), 'booking_cancellations', ['book_ref'], unique=False)
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hotel_id', sa.Integer(), nullable=False),
    sa.Column('book_ref', sa.String(length=32), nullable=False),
    sa.Column('booked_at', sa.DateTime(), nullable=False),
    sa.Column('arrival', sa.Date(), nullable=False),
    sa.Column('departure', sa.Date(), nullable=False),
    sa.Column('nights', sa.Integer(), nullable=False),
    sa.Column('room_type_code', sa.String(length=32), nullable=False),
    sa.Column('company_code', sa.String(length=64), nullable=True),
    sa.Column('agent_code', sa.String(length=64), nullable=True),
    sa.Column('adr_nett', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('value_nett', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('rate_plan', sa.String(length=64), nullable=True),
    sa.Column('market_segment', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['hotel_id'], ['hotels.id'], name=op.f('fk_bookings_hotel_id_hotels'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings')),
    sa.UniqueConstraint('hotel_id', 'book_ref', name=op.f('uq_bookings_hotel_id_book_ref'))
    )


def downgrade() -> None:
    op.drop_table('bookings')
    op.drop_index(op.f('ix_booking_cancellations_book_ref'), table_name='booking_cancellations')
    op.drop_table('booking_cancellations')
