"""Initial schema: feeds, articles, story_clusters with pgvector.

Revision ID: 001
Revises:
Create Date: 2026-03-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create story_clusters table
    op.create_table(
        "story_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("primary_article_id", sa.Integer(), nullable=True),
        sa.Column("article_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Create HNSW index on cluster embeddings
    op.execute(
        """
        CREATE INDEX ix_cluster_embedding
        ON story_clusters
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # Create feeds table
    op.create_table(
        "feeds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), unique=True, nullable=False),
        sa.Column("website_url", sa.String(2048), nullable=True),
        sa.Column("favicon_url", sa.String(2048), nullable=True),
        sa.Column(
            "trust_tier",
            sa.String(20),
            nullable=False,
            server_default="medium",
        ),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("region", sa.String(50), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "error_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "article_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Create articles table
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.String(2048), unique=True, nullable=False),
        sa.Column("url_hash", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("author", sa.String(512), nullable=True),
        sa.Column("image_url", sa.String(2048), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column(
            "is_opinion", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "is_wire_story",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("wire_source", sa.String(100), nullable=True),
        sa.Column(
            "fact_check_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "cluster_id",
            sa.Integer(),
            sa.ForeignKey("story_clusters.id"),
            nullable=True,
        ),
        sa.Column(
            "feed_id",
            sa.Integer(),
            sa.ForeignKey("feeds.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("articles")
    op.drop_table("feeds")
    op.drop_table("story_clusters")
    op.execute("DROP EXTENSION IF EXISTS vector")
