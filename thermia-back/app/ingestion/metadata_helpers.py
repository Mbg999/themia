"""Pure-function helpers for extracting and normalizing legal-document metadata.

This module is intentionally side-effect-free: no I/O, no DB, no Cohere.
Every function takes plain inputs (strings, dicts) and returns plain outputs,
so the whole module is trivially unit-testable in isolation.

Public functions (consumed by `ingestion-wiring`):
    parse_frontmatter(md_text)     -> (dict, str)
    compute_content_hash(text)     -> str (64-char SHA256 hex)
    extract_legal_rank(fm, title)  -> str
    normalize_status(raw)          -> str
    derive_eli(fm)                 -> str | None
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_OPEN = "---\n"


def parse_frontmatter(md_text: str) -> tuple[dict, str]:
    """Split a Markdown string into (YAML-frontmatter-dict, body).

    Behaviour:
      - If the text does not begin with ``---\\n``, return ``({}, md_text)``.
      - Otherwise look for the next line containing only ``---``. If none is
        found, the block is malformed: return ``({}, md_text)``.
      - Parse the YAML block with ``yaml.safe_load``. On any exception, log a
        WARNING and return ``({}, md_text)``.
      - If the parsed value is not a dict (e.g. a list, scalar, or ``None``),
        return ``({}, md_text)``.
      - Otherwise return ``(frontmatter_dict, body_after_closing_marker)``.

    The body returned in the success case is everything after the closing
    ``---`` line, *including* the newline that follows it (so callers can
    safely concatenate or split it again without losing structure).
    """
    if not md_text.startswith(_FRONTMATTER_OPEN):
        return {}, md_text

    # Search for a closing "---" on its own line, starting after the opener.
    # We accept "\n---\n" (closer with following newline) or "\n---" at EOF.
    rest = md_text[len(_FRONTMATTER_OPEN):]
    # Find a line that is exactly "---" — must be at the start of a line and
    # followed by either a newline or EOF. We deliberately leave that trailing
    # newline (if any) in the body so callers see the same structure they'd
    # see if they'd split on the closer themselves.
    match = re.search(r"(?:\A|\n)---(?=\n|\Z)", "\n" + rest)
    if match is None:
        return {}, md_text

    # `match` was computed against "\n" + rest, so subtract 1 for the prepended \n.
    closer_start = match.start() - 1  # index into `rest` where the "\n---" begins
    closer_end = match.end() - 1      # index into `rest` just past the "---"

    yaml_block = rest[:closer_start]
    body = rest[closer_end:]

    try:
        parsed = yaml.safe_load(yaml_block)
    except Exception as exc:  # noqa: BLE001 — yaml may raise many subclasses
        logger.warning("Failed to parse YAML frontmatter: %s", exc)
        return {}, md_text

    if not isinstance(parsed, dict):
        return {}, md_text

    return parsed, body


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------

_WS_RUN = re.compile(r"\s+")


def compute_content_hash(text: str) -> str:
    """Return a 64-char SHA256 hex digest of a whitespace-normalized text.

    Normalization: lowercase, collapse all whitespace runs (spaces, tabs,
    newlines) to a single space, then strip leading/trailing whitespace.

    The hash is stable across cosmetic edits (re-indentation, trailing
    whitespace, blank lines) so ingestion can skip re-embedding documents
    whose content hasn't meaningfully changed.
    """
    normalized = _WS_RUN.sub(" ", text.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# extract_legal_rank
# ---------------------------------------------------------------------------

# Order matters: more specific patterns first so "real decreto-ley" wins over
# "real decreto" and "ley orgánica" wins over plain "ley".
_RANK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bley\s+org[áa]nica\b", re.IGNORECASE), "ley_organica"),
    (re.compile(r"\breal\s+decreto[-\s]ley\b", re.IGNORECASE), "real_decreto_ley"),
    (re.compile(r"\breal\s+decreto\b", re.IGNORECASE), "real_decreto"),
    (re.compile(r"\bley\b", re.IGNORECASE), "ley"),
    (re.compile(r"\bdecreto\b", re.IGNORECASE), "decreto"),
    (re.compile(r"\borden\b", re.IGNORECASE), "orden"),
    (re.compile(r"\bresoluci[óo]n\b", re.IGNORECASE), "resolucion"),
]


def _normalize_rank_token(raw: str) -> str:
    """Normalize a free-form rank string into the canonical underscore form.

    Lowercases, replaces hyphens and runs of whitespace with underscores,
    and strips accents on the small set we care about (``ó``→``o``,
    ``á``→``a``).
    """
    lowered = raw.strip().lower()
    # Accent-strip for the handful of letters that appear in our rank vocabulary.
    lowered = lowered.replace("á", "a").replace("ó", "o")
    # Hyphens and any whitespace become underscores.
    lowered = re.sub(r"[-\s]+", "_", lowered)
    return lowered


# Set of canonical rank values we will accept from frontmatter normalization.
_KNOWN_RANKS = {
    "ley_organica",
    "real_decreto_ley",
    "real_decreto",
    "ley",
    "decreto",
    "orden",
    "resolucion",
}


def extract_legal_rank(frontmatter: dict, law_title: str) -> str:
    """Return a canonical legal-rank token, or ``""`` if none can be determined.

    Resolution order:
      1. ``frontmatter["rank"]`` — if non-empty, normalize and return it.
      2. Scan ``law_title`` with the patterns in ``_RANK_PATTERNS`` (most
         specific first) and return the first match's canonical token.
      3. Otherwise return ``""``.

    Canonical tokens: ``ley_organica``, ``real_decreto_ley``, ``real_decreto``,
    ``ley``, ``decreto``, ``orden``, ``resolucion``.
    """
    raw_rank = frontmatter.get("rank", "")
    if isinstance(raw_rank, str) and raw_rank.strip():
        normalized = _normalize_rank_token(raw_rank)
        if normalized in _KNOWN_RANKS:
            return normalized
        # Unknown frontmatter value — fall through to title-based detection.

    if law_title:
        for pattern, canonical in _RANK_PATTERNS:
            if pattern.search(law_title):
                return canonical

    return ""


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------

# Case-insensitive mapping from raw status tokens to canonical Spanish values.
_STATUS_MAP: dict[str, str] = {
    "in_force": "vigente",
    "in force": "vigente",
    "vigente": "vigente",
    "derogated": "derogada",
    "derogada": "derogada",
    "repealed": "derogada",
    "partially_in_force": "parcialmente vigente",
    "parcialmente vigente": "parcialmente vigente",
    "partial": "parcialmente vigente",
}


def normalize_status(raw: Optional[str]) -> str:
    """Normalize a raw status string to a canonical Spanish domain value.

    Returns one of ``"vigente"``, ``"derogada"``, ``"parcialmente vigente"``,
    or ``""`` for unknown/empty/None input. Unknown non-empty values produce
    a WARNING log entry.
    """
    if raw is None:
        return ""
    key = raw.strip().lower()
    if not key:
        return ""
    mapped = _STATUS_MAP.get(key)
    if mapped is not None:
        return mapped
    logger.warning("Unknown legal status value: %r", raw)
    return ""


# ---------------------------------------------------------------------------
# derive_eli
# ---------------------------------------------------------------------------

_ELI_IN_URL = re.compile(r"/eli/(.+)$")


def _extract_eli_from_url(url: str) -> Optional[str]:
    """Return ``"eli/<rest>"`` if ``url`` contains an ``/eli/`` segment, else None."""
    match = _ELI_IN_URL.search(url)
    if match is None:
        return None
    return "eli/" + match.group(1).strip().rstrip("/")


def derive_eli(frontmatter: dict) -> Optional[str]:
    """Conservatively derive an ELI identifier from frontmatter.

    Resolution order:
      1. ``frontmatter["eli"]`` — return stripped value if non-empty.
      2. ``frontmatter["source"]`` — if it contains ``/eli/``, extract from
         that point onward.
      3. ``frontmatter["url"]`` — same URL extraction rule.
      4. Return ``None`` (explicitly, not ``""``) if nothing matches.

    Never raises: any non-string field is silently ignored.
    """
    direct = frontmatter.get("eli", "")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    source = frontmatter.get("source", "")
    if isinstance(source, str) and source:
        extracted = _extract_eli_from_url(source)
        if extracted is not None:
            return extracted

    url = frontmatter.get("url", "")
    if isinstance(url, str) and url:
        extracted = _extract_eli_from_url(url)
        if extracted is not None:
            return extracted

    return None
