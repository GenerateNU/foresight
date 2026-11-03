"""feedback

A manager can now say whether a night's rate is too high, too low or about
right, optionally give the rate they would charge, and say why: tags from a
fixed list, free text, or both. Feedback is kept per room type and night, and
it is added to, never changed: a new opinion is the next `version`, the highest
version is current, and earlier ones keep their times.

It records the recommendation snapshot the manager saw (null for a past night
that was never saved), whether it came before or after the night, and who gave
it (null for feedback saved before sign-in was required). Deleting a snapshot or a user keeps the
feedback and clears the link; deleting a hotel or room type removes it.

A new table; no existing data changes. A downgrade drops the table and every
piece of feedback in it.

Revision ID: 7d3b9e1f5a42
Revises: 0eca3135d066
Create Date: 2026-10-31 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7d3b9e1f5a42"
down_revision: Union[str, None] = "0eca3135d066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("room_type_id", sa.Integer(), nullable=False),
        sa.Column("stay_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column(
            "verdict",
            sa.Enum(
                "TOO_HIGH",
                "TOO_LOW",
                "ABOUT_RIGHT",
                name="feedbackverdict",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("rate", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column(
            "reason_tags",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column(
            "timing",
            sa.Enum(
                "BEFORE",
                "AFTER",
                name="feedbacktiming",
                native_enum=False,
                length=10,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rate > 0", name=op.f("ck_feedback_rate_positive")),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
            name=op.f("fk_feedback_hotel_id_hotels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_type_id"],
            ["room_types.id"],
            name=op.f("fk_feedback_room_type_id_room_types"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["recommendation_snapshots.id"],
            name=op.f("fk_feedback_snapshot_id_recommendation_snapshots"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_feedback_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint(
            "hotel_id",
            "room_type_id",
            "stay_date",
            "version",
            name=op.f("uq_feedback_hotel_id_room_type_id_stay_date_version"),
        ),
    )
    op.create_index(
        op.f("ix_feedback_room_type_id"), "feedback", ["room_type_id"], unique=False
    )
    op.create_index(
        op.f("ix_feedback_snapshot_id"), "feedback", ["snapshot_id"], unique=False
    )
    op.create_index(op.f("ix_feedback_user_id"), "feedback", ["user_id"], unique=False)
    op.create_index(
        "ix_feedback_hotel_id_stay_date_created_at",
        "feedback",
        ["hotel_id", "stay_date", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_hotel_id_stay_date_created_at", table_name="feedback")
    op.drop_index(op.f("ix_feedback_user_id"), table_name="feedback")
    op.drop_index(op.f("ix_feedback_snapshot_id"), table_name="feedback")
    op.drop_index(op.f("ix_feedback_room_type_id"), table_name="feedback")
    op.drop_table("feedback")
