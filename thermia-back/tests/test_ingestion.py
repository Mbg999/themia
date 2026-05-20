"""
Unit tests for ingestion-pipeline (scripts/ingest.py).
All tests run without network or DB access — Ollama and DB are mocked.

Test IDs:
  ING-T3: parse_legal_structure — markdown parser
  ING-T4: chunk_article — token-based chunker
  ING-T4b: build_embedding_text — chunk text format
  ING-T5: Ollama embed invocation contract
  ING-T5b: retry logic on transient errors
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

    def test_h1_only_document_produces_one_chunk(self):
        """A law with H1 + body text but no H2/H3 must not be skipped."""
        parse_legal_structure = self._import()
        h1_only_md = (
            "# Real Orden de 18 de julio de 1887\n\n"
            "Ilmo. Sr.: Dada cuenta a S. M. del expediente instruído en esa Dirección "
            "general a virtud de las instancias elevadas.\n\n"
            "1.ª Que hayan de sepultarse los cadáveres.\n\n"
            "2.ª Que los gobernadores civiles reconozcan.\n"
        )
        chunks = parse_legal_structure(h1_only_md, source_file="es/BOE-A-1887-4896.md")
        assert len(chunks) == 1, f"Expected 1 chunk, got {len(chunks)}"

    def test_h1_only_chunk_uses_law_title_as_article(self):
        """For H1-only documents the article name falls back to the law title."""
        parse_legal_structure = self._import()
        h1_only_md = "# Ley de Prueba\n\nContenido de la ley sin artículos numerados.\n"
        chunks = parse_legal_structure(h1_only_md, source_file="prueba.md")
        assert chunks[0]["metadata"]["article"] == "Ley de Prueba"

    def test_h1_only_chunk_contains_body_text(self):
        """Body text under the H1 appears in chunk content."""
        parse_legal_structure = self._import()
        h1_only_md = "# Ley de Prueba\n\nEste es el contenido relevante.\n"
        chunks = parse_legal_structure(h1_only_md, source_file="prueba.md")
        assert "contenido relevante" in chunks[0]["content"]

    def test_lines_before_h1_are_not_included(self):
        """Raw frontmatter lines before the H1 must not pollute chunk content."""
        parse_legal_structure = self._import()
        md_with_preamble = (
            "title: Algo\nidentifier: BOE-X\n\n"
            "# Ley de Prueba\n\n"
            "Contenido real de la ley.\n"
        )
        chunks = parse_legal_structure(md_with_preamble, source_file="prueba.md")
        assert len(chunks) == 1
        assert "title: Algo" not in chunks[0]["content"]
        assert "identifier" not in chunks[0]["content"]

    def test_frontmatter_status_normalized_in_metadata(self):
        """status from YAML frontmatter is normalized and added to chunk metadata."""
        parse_legal_structure = self._import()
        md = (
            "---\nstatus: in_force\n---\n"
            "# Ley de Prueba\n\n### Artículo 1\n\nContenido.\n"
        )
        chunks = parse_legal_structure(md, source_file="prueba.md")
        assert chunks[0]["metadata"]["status"] == "vigente"

    def test_frontmatter_legal_rank_extracted_in_metadata(self):
        """rank from YAML frontmatter is normalized and added to chunk metadata."""
        parse_legal_structure = self._import()
        md = (
            "---\nrank: decreto\n---\n"
            "# Decreto de Prueba\n\n### Artículo 1\n\nContenido.\n"
        )
        chunks = parse_legal_structure(md, source_file="prueba.md")
        assert chunks[0]["metadata"]["legal_rank"] == "decreto"

    def test_frontmatter_country_sets_jurisdiction(self):
        """country field in frontmatter overrides the default jurisdiction."""
        parse_legal_structure = self._import()
        md = (
            "---\ncountry: es\n---\n"
            "# Ley de Prueba\n\n### Artículo 1\n\nContenido.\n"
        )
        chunks = parse_legal_structure(md, source_file="prueba.md")
        assert chunks[0]["metadata"]["jurisdiction"] == "ES"

    def test_source_metadata_contains_full_frontmatter(self):
        """source_metadata on each chunk is the raw frontmatter dict."""
        parse_legal_structure = self._import()
        md = (
            "---\nrank: orden\ndepartment: Min Interior\nstatus: in_force\n---\n"
            "# Real Orden\n\n### Artículo 1\n\nContenido.\n"
        )
        chunks = parse_legal_structure(md, source_file="prueba.md")
        sm = chunks[0]["source_metadata"]
        assert isinstance(sm, dict)
        assert sm["department"] == "Min Interior"
        assert sm["rank"] == "orden"

    def test_source_metadata_none_when_no_frontmatter(self):
        """source_metadata is None when the file has no frontmatter block."""
        parse_legal_structure = self._import()
        chunks = parse_legal_structure(SAMPLE_MD, source_file="lopj.md")
        assert all(c["source_metadata"] is None for c in chunks)

    def test_frontmatter_not_in_chunk_content(self):
        """YAML frontmatter text must never appear inside chunk content."""
        parse_legal_structure = self._import()
        md = (
            "---\ntitle: Decreto 1513/1959\nrank: decreto\nstatus: in_force\n---\n"
            "# Decreto 1513/1959\n\n### Artículo 1\n\nContenido de la norma.\n"
        )
        chunks = parse_legal_structure(md, source_file="BOE-A-1959-11603.md")
        for chunk in chunks:
            assert "rank: decreto" not in chunk["content"]
            assert "status: in_force" not in chunk["content"]
            assert "---" not in chunk["content"]


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



# ---------------------------------------------------------------------------
# ING-T5 tests: Ollama embed invocation
# ---------------------------------------------------------------------------

class TestOllamaEmbedding:
    """generate_embeddings calls ollama.embed with bge-m3 model.

    Covers: ING-T5
    Note: class name kept for git history continuity; tests now verify Ollama.
    """

    def _import(self):
        from scripts.ingest import generate_embeddings
        return generate_embeddings

    def _make_client_mock(self, embeddings):
        """Return a mock ollama.Client whose .embed() returns the given embeddings."""
        mock_client = MagicMock()
        mock_client.embed.return_value = {"embeddings": embeddings}
        return mock_client

    def test_calls_ollama_embed_with_bge_m3(self):
        """client.embed is called with model='bge-m3'."""
        generate_embeddings = self._import()
        mock_client = self._make_client_mock([[0.1] * 1024, [0.2] * 1024])

        with patch("ollama.Client", return_value=mock_client):
            generate_embeddings(["texto uno", "texto dos"])

        mock_client.embed.assert_called_once()
        call_kwargs = mock_client.embed.call_args.kwargs
        assert call_kwargs.get("model") == "bge-m3"

    def test_returns_list_of_float_vectors(self):
        """Result has 2 vectors of 1024 dimensions each."""
        generate_embeddings = self._import()
        mock_client = self._make_client_mock([[0.1] * 1024, [0.2] * 1024])

        with patch("ollama.Client", return_value=mock_client):
            result = generate_embeddings(["texto uno", "texto dos"])

        assert len(result) == 2
        assert len(result[0]) == 1024
        assert len(result[1]) == 1024

    def test_batches_multiple_texts_in_single_call(self):
        """3 texts (< batch size 50) → client.embed called once."""
        generate_embeddings = self._import()
        mock_client = self._make_client_mock([[0.1] * 1024] * 3)

        with patch("ollama.Client", return_value=mock_client):
            generate_embeddings(["t1", "t2", "t3"])

        assert mock_client.embed.call_count == 1

    def test_batch_boundary_51_texts_two_calls(self):
        """51 texts → client.embed called twice (50 + 1)."""
        generate_embeddings = self._import()
        mock_client = MagicMock()
        mock_client.embed.side_effect = [
            {"embeddings": [[0.1] * 1024] * 50},
            {"embeddings": [[0.2] * 1024] * 1},
        ]

        with patch("ollama.Client", return_value=mock_client):
            with patch("time.sleep"):  # skip inter-batch pause
                result = generate_embeddings(["text"] * 51)

        assert mock_client.embed.call_count == 2
        assert len(result) == 51


# ---------------------------------------------------------------------------
# ING-T5b tests: retry logic on transient errors
# ---------------------------------------------------------------------------

class TestOllamaRetryBehaviour:
    """generate_embeddings retries on transient errors (Ollama-based).

    Covers: ING-T5b
    Note: class name kept for git history continuity; tests now verify Ollama retry.
    """

    def _import(self):
        from scripts.ingest import generate_embeddings
        return generate_embeddings

    def test_retries_on_transient_error(self):
        """client.embed fails twice, succeeds on 3rd attempt → returns result."""
        generate_embeddings = self._import()

        ok_response = {"embeddings": [[0.5] * 1024]}
        mock_client = MagicMock()
        mock_client.embed.side_effect = [
            Exception("connection error"),
            Exception("connection error"),
            ok_response,
        ]

        with patch("ollama.Client", return_value=mock_client):
            with patch("time.sleep"):
                result = generate_embeddings(["texto"])

        assert mock_client.embed.call_count == 3
        assert len(result) == 1
        assert result[0] == [0.5] * 1024

    def test_raises_after_max_retries(self):
        """client.embed fails all 3 attempts (1 initial + 2 retries) → exception propagates."""
        generate_embeddings = self._import()

        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("persistent error")

        with patch("ollama.Client", return_value=mock_client):
            with patch("time.sleep"):
                with pytest.raises(Exception, match="persistent error"):
                    generate_embeddings(["texto"])

        # _EMBED_RETRY_COUNT = 2 → total attempts = 1 + 2 = 3
        assert mock_client.embed.call_count == 3

    def test_interbatch_sleep_pause(self):
        """51 texts → time.sleep called between batches (inter-batch pause)."""
        generate_embeddings = self._import()

        mock_client = MagicMock()
        mock_client.embed.side_effect = [
            {"embeddings": [[0.1] * 1024] * 50},
            {"embeddings": [[0.2] * 1024] * 1},
        ]

        with patch("ollama.Client", return_value=mock_client):
            with patch("time.sleep") as mock_sleep:
                generate_embeddings(["text"] * 51)

        # At least one sleep call for inter-batch pause
        assert mock_sleep.call_count >= 1


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

    def _make_chunk_with_meta(self, **overrides):
        chunk = self._make_chunk()
        chunk["metadata"].update(overrides)
        chunk.setdefault("source_metadata", None)
        return chunk

    def test_upsert_writes_status_column(self):
        """Document.status is populated from chunk metadata."""
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        chunk = self._make_chunk_with_meta(status="vigente")
        upsert_documents(MagicMock(return_value=mock_session), [chunk])

        doc = mock_session.merge.call_args[0][0]
        assert doc.status == "vigente"

    def test_upsert_writes_legal_rank_column(self):
        """Document.legal_rank is populated from chunk metadata."""
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        chunk = self._make_chunk_with_meta(legal_rank="decreto")
        upsert_documents(MagicMock(return_value=mock_session), [chunk])

        doc = mock_session.merge.call_args[0][0]
        assert doc.legal_rank == "decreto"

    def test_upsert_writes_source_metadata_column(self):
        """Document.source_metadata_ is populated from chunk source_metadata."""
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        chunk = self._make_chunk()
        chunk["source_metadata"] = {"department": "Min Interior", "rank": "decreto"}
        upsert_documents(MagicMock(return_value=mock_session), [chunk])

        doc = mock_session.merge.call_args[0][0]
        assert doc.source_metadata_ == {"department": "Min Interior", "rank": "decreto"}

    def test_upsert_source_metadata_none_when_absent(self):
        """Document.source_metadata_ is None when chunk has no source_metadata."""
        upsert_documents = self._import()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        chunk = self._make_chunk()  # no source_metadata key
        upsert_documents(MagicMock(return_value=mock_session), [chunk])

        doc = mock_session.merge.call_args[0][0]
        assert doc.source_metadata_ is None

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
