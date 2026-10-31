"""pricing model feedback

Each model version now records which manager feedback it was trained with: one
row per piece of feedback that changed a night's training rate or weight, with
whether the manager's rate replaced the recorded one, how much the night's
weight changed, and the rate the night was trained on. Without it, a version
couldn't say what it had learned from, and its accuracy couldn't be tied back
to the feedback behind it.

A new table; no existing data changes. Rows go with either side: deleting a
model version or a piece of feedback removes them. A downgrade drops the table
and every record in it.

Revision ID: b4e8a2c6d19f
Revises: 7d3b9e1f5a42
Create Date: 2026-10-31 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b4e8a2c6d19f"
down_revision: Union[str, None] = "7d3b9e1f5a42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pricing_model_feedback",
        sa.Column("pricing_model_id", sa.Integer(), nullable=False),
        sa.Column("feedback_id", sa.Integer(), nullable=False),
        sa.Column("rate_replaced", sa.Boolean(), nullable=False),
        sa.Column("weight_factor", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("training_rate", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["feedback.id"],
            name=op.f("fk_pricing_model_feedback_feedback_id_feedback"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_model_id"],
            ["pricing_models.id"],
            name=op.f("fk_pricing_model_feedback_pricing_model_id_pricing_models"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "pricing_model_id", "feedback_id", name=op.f("pk_pricing_model_feedback")
        ),
    )
    op.create_index(
        op.f("ix_pricing_model_feedback_feedback_id"),
        "pricing_model_feedback",
        ["feedback_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pricing_model_feedback_feedback_id"),
        table_name="pricing_model_feedback",
    )
    op.drop_table("pricing_model_feedback")
