"""users and user hotels

The API has no notion of who is calling it. Adds users, identified by their
Google account id (unique; email can change and is not), and a link table so a
hotel can have several users and a user can belong to several hotels. A user
with no link is allowed: they have signed up but work for no hotel yet. Links
are removed with either side.

Both tables are new, so existing data is untouched. A downgrade drops both
tables and every user and link in them.

Revision ID: e6235f613e08
Revises: 46b9cb210348
Create Date: 2026-10-25 19:17:46.437463

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e6235f613e08"
down_revision: Union[str, None] = "46b9cb210348"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("google_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_signed_in_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("google_id", name=op.f("uq_users_google_id")),
    )
    op.create_table(
        "user_hotels",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
            name=op.f("fk_user_hotels_hotel_id_hotels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_hotels_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "hotel_id", name=op.f("pk_user_hotels")),
    )
    op.create_index(
        op.f("ix_user_hotels_hotel_id"),
        "user_hotels",
        ["hotel_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_hotels_hotel_id"), table_name="user_hotels")
    op.drop_table("user_hotels")
    op.drop_table("users")
