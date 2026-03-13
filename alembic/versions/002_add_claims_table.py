"""Add claims table and fact-check columns to articles.

Revision ID: 002
Revises: 001
Create Date: 2026-03-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create claims table
    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("articles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(50), nullable=False),
        sa.Column("original_quote", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=True),
        sa.Column("confidence", sa.String(20), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("evidence_sources", sa.Text(), nullable=True),
        sa.Column("supporting_sources", sa.Text(), nullable=True),
        sa.Column("contradicting_sources", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Add fact-check columns to articles
    op.add_column("articles", sa.Column("accuracy_score", sa.Float(), nullable=True))
    op.add_column(
        "articles",
        sa.Column("fact_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "articles", sa.Column("fact_check_error", sa.Text(), nullable=True)
    )
    op.add_column(
        "articles",
        sa.Column("claim_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("articles", "claim_count")
    op.drop_column("articles", "fact_check_error")
    op.drop_column("articles", "fact_checked_at")
    op.drop_column("articles", "accuracy_score")
    op.drop_table("claims")
