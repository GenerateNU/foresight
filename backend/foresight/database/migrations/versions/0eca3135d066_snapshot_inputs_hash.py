"""snapshot inputs and inputs hash

A recommendation is now saved every time its inputs change, and reused while
they don't. Each snapshot records the inputs it was priced from (`inputs`) and
their fingerprint (`inputs_hash`); a request compares the fingerprint of the
night's current inputs with the latest snapshot's to decide. A reused snapshot
also needs its interval's coverage (`interval_level`) without loading the
model, so that is stored too.

Existing rows predate this and get empty inputs and an empty hash, which never
matches, so the first request for each of those nights saves one fresh row.
Their level is 0.8, the only level any model has been trained with.

Revision ID: 0eca3135d066
Revises: e6235f613e08
Create Date: 2026-10-27 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0eca3135d066"
down_revision: Union[str, None] = "e6235f613e08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recommendation_snapshots",
        sa.Column(
            "interval_level",
            sa.Float(),
            server_default=sa.text("0.8"),
            nullable=False,
        ),
    )
    op.add_column(
        "recommendation_snapshots",
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "recommendation_snapshots",
        sa.Column(
            "inputs_hash",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
    )
    # The defaults only fill existing rows; new rows always set both.
    op.alter_column("recommendation_snapshots", "interval_level", server_default=None)
    op.alter_column("recommendation_snapshots", "inputs", server_default=None)
    op.alter_column("recommendation_snapshots", "inputs_hash", server_default=None)


def downgrade() -> None:
    op.drop_column("recommendation_snapshots", "inputs_hash")
    op.drop_column("recommendation_snapshots", "inputs")
    op.drop_column("recommendation_snapshots", "interval_level")
