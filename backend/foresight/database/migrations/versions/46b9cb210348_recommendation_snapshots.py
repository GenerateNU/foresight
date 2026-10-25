"""recommendation snapshots

Every recommended rate is now saved: one row per room type and night each
time recommendations are produced, with the pricing model and version that
produced it, the rate, its interval and uncertainty, the factor breakdown,
and when it was made. Rows are only ever added, so a night keeps its full
history of rates.

Without this, a recommendation was computed and discarded, so we couldn't
show how a night's rate changed since the last update, tie a manager's
feedback to the rate they saw, or check later how good a rate was.

A new table; no existing data changes. A downgrade drops the table and
every snapshot in it.

Revision ID: 46b9cb210348
Revises: 4c1e7a9d2b10
Create Date: 2026-10-24 20:12:30.793617

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "46b9cb210348"
down_revision: Union[str, None] = "4c1e7a9d2b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("room_type_id", sa.Integer(), nullable=False),
        sa.Column("stay_date", sa.Date(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=60), nullable=False),
        sa.Column("rate", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("interval_low", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("interval_high", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("uncertainty", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("factors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
            name=op.f("fk_recommendation_snapshots_hotel_id_hotels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["pricing_models.id"],
            name=op.f("fk_recommendation_snapshots_model_id_pricing_models"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_type_id"],
            ["room_types.id"],
            name=op.f("fk_recommendation_snapshots_room_type_id_room_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation_snapshots")),
    )
    op.create_index(
        op.f("ix_recommendation_snapshots_hotel_id"),
        "recommendation_snapshots",
        ["hotel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recommendation_snapshots_model_id"),
        "recommendation_snapshots",
        ["model_id"],
        unique=False,
    )
    op.create_index(
        "ix_recommendation_snapshots_room_type_id_stay_date_created_at",
        "recommendation_snapshots",
        ["room_type_id", "stay_date", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_snapshots_room_type_id_stay_date_created_at",
        table_name="recommendation_snapshots",
    )
    op.drop_index(
        op.f("ix_recommendation_snapshots_model_id"),
        table_name="recommendation_snapshots",
    )
    op.drop_index(
        op.f("ix_recommendation_snapshots_hotel_id"),
        table_name="recommendation_snapshots",
    )
    op.drop_table("recommendation_snapshots")
