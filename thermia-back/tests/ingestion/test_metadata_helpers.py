"""Tests for app.ingestion.metadata_helpers.

Pure-function tests — no I/O, no DB, no Cohere. Each of the 5 public functions
has its own test class with multiple cases covering happy path and edge cases.
"""

from __future__ import annotations

import hashlib
import logging

import pytest

from app.ingestion.metadata_helpers import (
    compute_content_hash,
    derive_eli,
    extract_legal_rank,
    normalize_status,
    parse_frontmatter,
)


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_returns_empty_dict_and_original_when_no_frontmatter(self) -> None:
        text = "# No frontmatter"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_parses_basic_frontmatter_block(self) -> None:
        fm, body = parse_frontmatter("---\ntitle: X\n---\n# H1")
        assert fm == {"title": "X"}
        assert body == "\n# H1"

    def test_parses_multiple_keys(self) -> None:
        text = "---\ntitle: Ley\nrank: ley\nyear: 2007\n---\nBody text"
        fm, body = parse_frontmatter(text)
        assert fm == {"title": "Ley", "rank": "ley", "year": 2007}
        # Body retains the newline that followed the closing "---" marker,
        # matching the spec's `parse_frontmatter("---\\ntitle: X\\n---\\n# H1")`
        # → `({"title": "X"}, "\\n# H1")` acceptance case.
        assert body == "\nBody text"

    def test_malformed_yaml_returns_empty_and_original(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        text = "---\n: broken\n---\n# H1"
        with caplog.at_level(logging.WARNING):
            fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text
        # A WARNING about the parse failure must have been logged.
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)

    def test_yaml_block_that_is_not_a_dict_returns_empty(self) -> None:
        # A bare list at the top of the YAML block — valid YAML but not a dict.
        text = "---\n- one\n- two\n---\nbody"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_text_starting_with_dashes_but_no_closing_marker(self) -> None:
        # Opens a frontmatter block but never closes it — treat as "no frontmatter".
        text = "---\ntitle: X\nno closer here"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_empty_string(self) -> None:
        fm, body = parse_frontmatter("")
        assert fm == {}
        assert body == ""


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_whitespace_and_case_are_normalized(self) -> None:
        assert compute_content_hash("  Hello  World  ") == compute_content_hash(
            "hello world"
        )

    def test_returns_64_char_hex(self) -> None:
        digest = compute_content_hash("anything")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_different_content_yields_different_hash(self) -> None:
        assert compute_content_hash("alpha") != compute_content_hash("beta")

    def test_matches_known_sha256(self) -> None:
        # After normalization "Hello World" → "hello world"
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert compute_content_hash("Hello World") == expected

    def test_collapses_tabs_and_newlines(self) -> None:
        assert compute_content_hash("a\tb\n\nc") == compute_content_hash("a b c")


# ---------------------------------------------------------------------------
# extract_legal_rank
# ---------------------------------------------------------------------------


class TestExtractLegalRank:
    def test_frontmatter_rank_takes_priority(self) -> None:
        assert extract_legal_rank({"rank": "real-decreto"}, "") == "real_decreto"

    def test_frontmatter_rank_with_spaces_is_normalized(self) -> None:
        assert (
            extract_legal_rank({"rank": "Ley Orgánica"}, "Some unrelated title")
            == "ley_organica"
        )

    def test_title_pattern_ley_organica(self) -> None:
        assert extract_legal_rank({}, "Ley Orgánica 3/2007") == "ley_organica"

    def test_title_pattern_real_decreto_ley_more_specific_than_real_decreto(
        self,
    ) -> None:
        assert (
            extract_legal_rank({}, "Real Decreto-ley 6/2012") == "real_decreto_ley"
        )

    def test_title_pattern_real_decreto(self) -> None:
        assert extract_legal_rank({}, "Real Decreto 463/2020") == "real_decreto"

    def test_title_pattern_plain_ley(self) -> None:
        assert extract_legal_rank({}, "Ley 39/2015 de Procedimiento") == "ley"

    def test_title_pattern_decreto(self) -> None:
        assert extract_legal_rank({}, "Decreto 100/2010") == "decreto"

    def test_title_pattern_orden(self) -> None:
        assert extract_legal_rank({}, "Orden ECD/65/2015") == "orden"

    def test_title_pattern_resolucion_with_accent(self) -> None:
        assert extract_legal_rank({}, "Resolución de 12 de mayo") == "resolucion"

    def test_title_pattern_resolucion_without_accent(self) -> None:
        assert extract_legal_rank({}, "Resolucion administrativa") == "resolucion"

    def test_unknown_title_returns_empty(self) -> None:
        assert extract_legal_rank({}, "Texto sin rango") == ""

    def test_empty_frontmatter_rank_falls_through_to_title(self) -> None:
        # rank="" should not short-circuit; it should fall through to the title.
        assert extract_legal_rank({"rank": ""}, "Ley 1/2000") == "ley"


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------


class TestNormalizeStatus:
    def test_in_force_english_maps_to_vigente(self) -> None:
        assert normalize_status("in_force") == "vigente"

    def test_in_force_with_space_maps_to_vigente(self) -> None:
        assert normalize_status("in force") == "vigente"

    def test_vigente_passes_through(self) -> None:
        assert normalize_status("vigente") == "vigente"

    def test_case_insensitive(self) -> None:
        assert normalize_status("VIGENTE") == "vigente"

    def test_derogated_variants(self) -> None:
        assert normalize_status("derogated") == "derogada"
        assert normalize_status("derogada") == "derogada"
        assert normalize_status("repealed") == "derogada"

    def test_partial_variants(self) -> None:
        assert normalize_status("partially_in_force") == "parcialmente vigente"
        assert normalize_status("parcialmente vigente") == "parcialmente vigente"
        assert normalize_status("partial") == "parcialmente vigente"

    def test_none_returns_empty_string(self) -> None:
        assert normalize_status(None) == ""

    def test_empty_string_returns_empty_string(self) -> None:
        assert normalize_status("") == ""

    def test_unknown_value_logs_warning_and_returns_empty(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = normalize_status("totally unknown status")
        assert result == ""
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)


# ---------------------------------------------------------------------------
# derive_eli
# ---------------------------------------------------------------------------


class TestDeriveEli:
    def test_direct_eli_field_is_used_first(self) -> None:
        assert (
            derive_eli({"eli": "eli/es/l/2007/003"}) == "eli/es/l/2007/003"
        )

    def test_eli_field_is_stripped(self) -> None:
        assert derive_eli({"eli": "  eli/es/l/2007/003  "}) == "eli/es/l/2007/003"

    def test_source_url_with_eli_segment_is_extracted(self) -> None:
        assert (
            derive_eli({"source": "https://boe.es/eli/es/rd/2023/001"})
            == "eli/es/rd/2023/001"
        )

    def test_url_field_with_eli_segment_is_extracted(self) -> None:
        assert (
            derive_eli({"url": "https://example.org/eli/es/lo/2007/003/dof"})
            == "eli/es/lo/2007/003/dof"
        )

    def test_returns_none_when_nothing_found(self) -> None:
        assert derive_eli({}) is None

    def test_source_without_eli_returns_none(self) -> None:
        assert (
            derive_eli(
                {"source": "https://boe.es/diario_boe/txt.php?id=BOE-A-2023-001"}
            )
            is None
        )

    def test_eli_takes_priority_over_source(self) -> None:
        result = derive_eli(
            {
                "eli": "eli/es/l/2007/003",
                "source": "https://boe.es/eli/es/rd/2023/001",
            }
        )
        assert result == "eli/es/l/2007/003"

    def test_empty_eli_field_falls_through_to_source(self) -> None:
        # eli="" should not short-circuit; it should fall through to source.
        result = derive_eli(
            {"eli": "", "source": "https://boe.es/eli/es/rd/2023/001"}
        )
        assert result == "eli/es/rd/2023/001"
