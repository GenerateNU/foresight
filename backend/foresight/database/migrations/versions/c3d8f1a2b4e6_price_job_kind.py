"""price job kind

`jobs.kind` is a VARCHAR without a CHECK, so the new PRICE kind needs no schema
change. Older code can't load PRICE rows, so a downgrade deletes them; jobs are
run history, not data.

Revision ID: c3d8f1a2b4e6
Revises: 9a4c2e7b1d35
Create Date: 2026-11-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3d8f1a2b4e6'
down_revision: Union[str, None] = '9a4c2e7b1d35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind = 'PRICE'")
