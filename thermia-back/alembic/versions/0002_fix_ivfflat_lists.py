"""Fix ivfflat index: add WITH (lists=50) for correct ANN recall.

The initial migration created the index without WITH (lists=...), which defaults
to lists=100. Combined with pgvector's default probes=1, this yields ~1% recall
per query. This migration drops and recreates the index with lists=50, tuned for
the expected corpus size of 10k–50k chunks (rule of thumb: sqrt(doc_count)).

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_embedding")
    op.execute(
        "CREATE INDEX idx_documents_embedding ON documents "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists=50)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_embedding")
    op.execute(
        "CREATE INDEX idx_documents_embedding ON documents "
        "USING ivfflat (embedding vector_cosine_ops)"
    )
