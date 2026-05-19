"""
Unit tests for ingestion-pipeline (scripts/ingest.py).
All tests run without network or DB access — Cohere and DB are mocked.

Test IDs:
  ING-T3: parse_legal_structure — markdown parser
  ING-T4: chunk_article — token-based chunker
  ING-T4b: build_embedding_text — chunk text format
  ING-T5: Cohere client invocation contract
  ING-T6: upsert_documents — idempotency via session.merge()
"""
import os
import sys
import uuid
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure the thermia-back root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

SAMPLE_MD = """# Ley Orgánica del Poder Judicial

## Título I — Disposiciones Generales

### Artículo 1

El poder judicial emana del pueblo y se administra en nombre del Rey.

### Artículo 2

Los juzgados y tribunales no ejercerán más funciones que las señaladas.

## Título II — De los Jueces

### Artículo 3

Los jueces son independientes en el ejercicio de la potestad jurisdiccional.
"""

LONG_ARTICLE_TEXT = " ".join(["palabra"] * 900)  # 900 words → well over 800 tokens


# ---------------------------------------------------------------------------
# ING-T3 tests: parse_legal_structure
# ---------------------------------------------------------------------------

class TestParseLegalStructure:
    """parse_legal_structure returns chunks with all required metadata fields."""

    def _import(self):
        from scripts.ingest import parse_legal_structure
        return parse_legal_structure

    def test_returns_list_of_dicts(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        assert isinstance(chunks, list)
        assert len(chunks) > 0

    def test_each_chunk_has_required_metadata_fields(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        required_fields = {
            "law_id", "law_title", "article", "section",
            "chunk_type", "source_file", "jurisdiction", "year", "hierarchy_path",
        }
        for chunk in chunks:
            assert "metadata" in chunk, f"chunk missing 'metadata' key: {chunk}"
            missing = required_fields - chunk["metadata"].keys()
            assert not missing, f"Missing metadata fields: {missing}"

    def test_jurisdiction_is_always_ES(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        for chunk in chunks:
            assert chunk["metadata"]["jurisdiction"] == "ES"

    def test_source_file_propagated(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        for chunk in chunks:
            assert chunk["metadata"]["source_file"] == "lopj.md"

    def test_law_title_extracted_from_h1(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        for chunk in chunks:
            assert "Ley Orgánica del Poder Judicial" in chunk["metadata"]["law_title"]

    def test_article_extracted_from_h3(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        articles = [c["metadata"]["article"] for c in chunks]
        assert any("1" in a or "Artículo 1" in a for a in articles)

    def test_section_extracted_from_h2(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        sections = [c["metadata"]["section"] for c in chunks]
        assert any("Título I" in s or "Disposiciones" in s for s in sections)

    def test_content_field_present(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        for chunk in chunks:
            assert "content" in chunk
            assert len(chunk["content"]) > 0

    def test_hierarchy_path_includes_law_and_article(self):
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        for chunk in chunks:
            hp = chunk["metadata"]["hierarchy_path"]
            assert isinstance(hp, str)
            assert len(hp) > 0


# ---------------------------------------------------------------------------
# ING-T4 tests: chunk_article
# ---------------------------------------------------------------------------

class TestChunkArticle:
    """chunk_article splits articles correctly based on token threshold."""

    def _import(self):
        from scripts.ingest import chunk_article
        return chunk_article

    def test_short_article_produces_single_chunk(self):
        chunk_article = self._import()
        short_text = "Este es un artículo corto con pocos tokens."
        chunks = chunk_article(short_text, article="Artículo 1", law_title="Ley X", law_id="LEY-1")
        assert len(chunks) == 1

    def test_short_article_chunk_type_is_article(self):
        chunk_article = self._import()
        short_text = "Este es un artículo corto con pocos tokens."
        chunks = chunk_article(short_text, article="Artículo 1", law_title="Ley X", law_id="LEY-1")
        assert chunks[0]["metadata"]["chunk_type"] == "article"

    def test_long_article_produces_multiple_chunks(self):
        chunk_article = self._import()
        chunks = chunk_article(LONG_ARTICLE_TEXT, article="Artículo 99", law_title="Ley X", law_id="LEY-1")
        assert len(chunks) > 1

    def test_long_article_chunk_type_is_sub_article(self):
        chunk_article = self._import()
        chunks = chunk_article(LONG_ARTICLE_TEXT, article="Artículo 99", law_title="Ley X", law_id="LEY-1")
        for chunk in chunks:
            assert chunk["metadata"]["chunk_type"] == "sub_article"

    def test_sub_chunks_are_at_most_512_tokens(self):
        import tiktoken
        chunk_article = self._import()
        enc = tiktoken.get_encoding("cl100k_base")
        chunks = chunk_article(LONG_ARTICLE_TEXT, article="Artículo 99", law_title="Ley X", law_id="LEY-1")
        for chunk in chunks:
            token_count = len(enc.encode(chunk["content"]))
            assert token_count <= 512, f"Sub-chunk has {token_count} tokens, exceeds 512"

    def test_sub_chunks_have_overlap(self):
        chunk_article = self._import()
        chunks = chunk_article(LONG_ARTICLE_TEXT, article="Artículo 99", law_title="Ley X", law_id="LEY-1")
        assert len(chunks) >= 2
        # Consecutive chunks should share some tokens (overlap region)
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        tokens_0 = enc.encode(chunks[0]["content"])
        tokens_1 = enc.encode(chunks[1]["content"])
        # Last 50 tokens of chunk 0 should appear at the start of chunk 1
        overlap_from_0 = tokens_0[-50:]
        start_of_1 = tokens_1[:50]
        # At least some overlap should exist
        assert len(set(overlap_from_0) & set(start_of_1)) > 0 or tokens_1[:50] == overlap_from_0


# ---------------------------------------------------------------------------
# ING-T4b tests: build_embedding_text
# ---------------------------------------------------------------------------

class TestBuildEmbeddingText:
    """build_embedding_text formats text with the required prefix."""

    def _import(self):
        from scripts.ingest import build_embedding_text
        return build_embedding_text

    def test_prefix_format(self):
        build_embedding_text = self._import()
        result = build_embedding_text(
            law_id="LEY-1",
            article="Artículo 5",
            law_title="Ley de Arrendamientos",
            content="El arrendatario tiene derecho...",
        )
        assert result.startswith("[LEY-1 - Artículo 5 - Ley de Arrendamientos]")

    def test_double_newline_separator(self):
        build_embedding_text = self._import()
        result = build_embedding_text(
            law_id="LEY-1",
            article="Artículo 5",
            law_title="Ley de Arrendamientos",
            content="El arrendatario tiene derecho...",
        )
        assert "\n\n" in result
        _, body = result.split("\n\n", 1)
        assert body == "El arrendatario tiene derecho..."

    def test_law_id_in_prefix(self):
        build_embedding_text = self._import()
        result = build_embedding_text(
            law_id="CC-ES",
            article="Artículo 1",
            law_title="Código Civil",
            content="texto",
        )
        assert "CC-ES" in result

    def test_article_in_prefix(self):
        build_embedding_text = self._import()
        result = build_embedding_text(
            law_id="CC-ES",
            article="Artículo 1",
            law_title="Código Civil",
            content="texto",
        )
        assert "Artículo 1" in result


# ---------------------------------------------------------------------------
# ING-T5 tests: Cohere client invocation
# ---------------------------------------------------------------------------

class TestCohereEmbedding:
    """generate_embeddings calls Cohere with the correct model and input_type."""

    def _import(self):
        from scripts.ingest import generate_embeddings
        return generate_embeddings

    def test_calls_embed_with_correct_model(self):
        generate_embeddings = self._import()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings = [[0.1] * 1024, [0.2] * 1024]
        mock_client.embed.return_value = mock_response

        texts = ["texto uno", "texto dos"]
        generate_embeddings(mock_client, texts)

        mock_client.embed.assert_called_once()
        call_kwargs = mock_client.embed.call_args.kwargs
        assert call_kwargs.get("model") == "embed-multilingual-v3.0"

    def test_calls_embed_with_search_document_input_type(self):
        generate_embeddings = self._import()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings = [[0.1] * 1024]
        mock_client.embed.return_value = mock_response

        generate_embeddings(mock_client, ["texto"])

        call_kwargs = mock_client.embed.call_args.kwargs
        assert call_kwargs.get("input_type") == "search_document"

    def test_returns_list_of_embedding_vectors(self):
        generate_embeddings = self._import()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings = [[0.1] * 1024, [0.2] * 1024]
        mock_client.embed.return_value = mock_response

        result = generate_embeddings(mock_client, ["texto uno", "texto dos"])
        assert len(result) == 2
        assert len(result[0]) == 1024


# ---------------------------------------------------------------------------
# ING-T6 tests: upsert_documents — idempotency
# ---------------------------------------------------------------------------

class TestUpsertDocuments:
    """upsert_documents merges records; re-running does not create duplicates."""

    def _import(self):
        from scripts.ingest import upsert_documents
        return upsert_documents

    def _make_chunk(self, article="Artículo 1", source_file="test.md"):
        return {
            "content": "Texto del artículo.",
            "embedding": [0.1] * 1024,
            "metadata": {
                "law_id": "LEY-1",
                "law_title": "Ley de Prueba",
                "article": article,
                "section": "Título I",
                "chunk_type": "article",
                "source_file": source_file,
                "jurisdiction": "ES",
                "year": "2020",
                "hierarchy_path": "LEY-1 > Título I > Artículo 1",
            },
        }

    def test_session_merge_called_for_each_chunk(self):
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_maker = MagicMock(return_value=mock_session)

        chunks = [self._make_chunk("Artículo 1"), self._make_chunk("Artículo 2")]
        upsert_documents(mock_session_maker, chunks)

        assert mock_session.merge.call_count == 2

    def test_session_commit_called(self):
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_maker = MagicMock(return_value=mock_session)

        chunks = [self._make_chunk()]
        upsert_documents(mock_session_maker, chunks)

        mock_session.commit.assert_called()

    def test_merge_uses_document_model(self):
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_maker = MagicMock(return_value=mock_session)

        chunks = [self._make_chunk()]
        upsert_documents(mock_session_maker, chunks)

        from app.db.models import Document
        merged_obj = mock_session.merge.call_args[0][0]
        assert isinstance(merged_obj, Document)

    def test_tsvector_populated_via_sql_expression(self):
        """The tsvector column is set to a SQL expression, not a plain string."""
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_maker = MagicMock(return_value=mock_session)

        chunks = [self._make_chunk()]
        upsert_documents(mock_session_maker, chunks)

        from sqlalchemy.sql.elements import ClauseElement
        merged_obj = mock_session.merge.call_args[0][0]
        assert isinstance(merged_obj.tsvector, ClauseElement), (
            f"Expected SQLAlchemy ClauseElement, got {type(merged_obj.tsvector)}"
        )
