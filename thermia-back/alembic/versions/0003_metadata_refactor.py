"""Metadata refactor: add status / legal_rank / jurisdiction / source_metadata columns + indexes.

Adds four new columns to the `documents` table to support two-layer metadata
storage (curated `metadata` JSONB vs raw `source_metadata` JSONB) and three
legal-filtering scalar columns (`status`, `legal_rank`, `jurisdiction`).
Also creates B-tree indexes on the three scalars and a GIN index on the
curated `metadata` column for efficient JSONB containment queries.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New scalar columns for legal filtering
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS status VARCHAR(32)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS legal_rank VARCHAR(64)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS jurisdiction VARCHAR(8)")

    # Raw provider metadata payload (two-layer metadata: curated vs raw)
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_metadata JSONB")

    # B-tree indexes for equality / IN filtering on the scalar legal columns
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_status ON documents (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_legal_rank ON documents (legal_rank)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_jurisdiction ON documents (jurisdiction)")

    # GIN index with jsonb_path_ops on the curated metadata column for
    # efficient containment (@>) queries.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_metadata_gin "
        "ON documents USING gin (metadata jsonb_path_ops)"
    )


def downgrade() -> None:
    # Drop indexes first (reverse order), then columns (reverse order)
    op.execute("DROP INDEX IF EXISTS ix_documents_metadata_gin")
    op.execute("DROP INDEX IF EXISTS ix_documents_jurisdiction")
    op.execute("DROP INDEX IF EXISTS ix_documents_legal_rank")
    op.execute("DROP INDEX IF EXISTS ix_documents_status")

    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS source_metadata")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS jurisdiction")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS legal_rank")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS status")
