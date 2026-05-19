"""Initial schema: documents table with pgvector extension.

Revision ID: 0001
Revises:
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable the pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create the documents table
    op.execute(
        """
        CREATE TABLE documents (
            id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content  TEXT NOT NULL,
            embedding vector(1024),
            tsvector  tsvector,
            metadata  JSONB DEFAULT '{}'
        )
        """
    )

    # ivfflat index on embedding for approximate nearest-neighbour search
    op.execute(
        "CREATE INDEX idx_documents_embedding ON documents "
        "USING ivfflat (embedding vector_cosine_ops)"
    )

    # GIN index on tsvector for full-text search
    op.execute(
        "CREATE INDEX idx_documents_tsvector ON documents USING GIN (tsvector)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
