"""job kinds per signal

Ingest and backfill merged into one job kind per signal (WEATHER, EVENTS,
PERFORMANCE); a request's dates choose refresh or backfill. `jobs.kind` is a
VARCHAR without a CHECK, so no schema changes, but rows of the old kinds
would no longer load. Jobs are run history, not data, so those rows are
deleted; a downgrade deletes rows of the new kinds the same way.

Revision ID: 80bab95951e7
Revises: 916e453d1325
Create Date: 2026-10-15 03:41:10.716151

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '80bab95951e7'
down_revision: Union[str, None] = '916e453d1325'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind NOT IN ('WEATHER', 'EVENTS', 'PERFORMANCE')")


def downgrade() -> None:
    op.execute("DELETE FROM jobs WHERE kind IN ('WEATHER', 'EVENTS', 'PERFORMANCE')")
