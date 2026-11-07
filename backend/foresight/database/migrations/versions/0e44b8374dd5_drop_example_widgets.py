"""drop example widgets

The Widget reference slice is gone; city.py is the slice to copy now. A
downgrade recreates the table empty.

Revision ID: 0e44b8374dd5
Revises: 53a9a680016f
Create Date: 2026-11-07 13:21:29.248693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e44b8374dd5'
down_revision: Union[str, None] = '53a9a680016f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('example_widgets')


def downgrade() -> None:
    op.create_table('example_widgets',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('name', sa.VARCHAR(length=120), autoincrement=False, nullable=False),
    sa.Column('description', sa.VARCHAR(length=500), autoincrement=False, nullable=True),
    sa.Column('quantity', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_example_widgets'))
    )
