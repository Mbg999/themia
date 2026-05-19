"""
Thermia ingestion pipeline CLI.

Clones https://github.com/legalize-dev/legalize-es, scans all .md files,
parses Spanish legal structure (H1=law, H2=title/section, H3+=article),
chunks each article, generates Cohere embeddings, and upserts into the
`documents` table idempotently.

Usage:
    python3 scripts/ingest.py [--reset]

Environment variables (all read from .env when THERMIA_ENV=local):
    THERMIA_ENV          — "local" or "production"
    SSH_HOST             — SSH bastion host (local only)
    SSH_USER             — SSH username (local only)
    SSH_PASSWORD         — SSH password (local only)
    SSH_REMOTE_BIND_PORT — PostgreSQL port on the remote (local only)
    DB_USER              — PostgreSQL user (local only)
    DB_PASSWORD          — PostgreSQL password (local only)
    DB_NAME              — PostgreSQL database name (local only)
    DATABASE_URL         — full connection URL (production only)
    COHERE_API_KEYS      — JSON array of Cohere API keys, e.g. '["key1","key2"]'
                           (legacy: COHERE_API_KEY scalar also accepted)
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import tiktoken

# ---------------------------------------------------------------------------
# Make `thermia-back/` importable when the script is invoked directly
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Deferred heavy imports so unit-tests can import pure functions without
# triggering the DB / Cohere imports (which require real env vars).

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

_REPO_URL = "https://github.com/legalize-dev/legalize-es"
_REPO_DIR = Path("/tmp/legalize-es")
# Pin to a specific commit so upstream changes cannot silently alter ingested data.
# Update this hash deliberately after reviewing upstream changes.
_REPO_COMMIT = "2ffdecd513fabf778aaeefdbbca2c5e409de9df6"

# Token thresholds
_CHUNK_THRESHOLD = 800   # articles ≤ this produce a single chunk
_SUB_CHUNK_SIZE = 512    # maximum tokens per sub-chunk
_OVERLAP = 50            # token overlap between consecutive sub-chunks

# Cohere rate-limit handling
_EMBED_BATCH_SIZE = 50              # max texts per embed() call (trial: 100 calls/min)
_EMBED_RETRY_DELAYS = (10, 30, 60)  # seconds to wait on successive 429s
# Configurable via EMBED_INTER_BATCH_SLEEP — use 0.05 on paid Cohere tier
_EMBED_INTER_BATCH_SLEEP = float(os.environ.get("EMBED_INTER_BATCH_SLEEP", "1.0"))

# Tiktoken encoding — cl100k_base is compatible with multilingual models
_ENC = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Pure functions (importable without real DB / Cohere)
# ---------------------------------------------------------------------------


def _count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def build_embedding_text(*, law_id: str, article: str, law_title: str, content: str) -> str:
    """Return the prefixed text sent to Cohere for embedding.

    Format: ``[LAW_ID - ARTICLE - LAW_TITLE]\\n\\ncontent``
    """
    prefix = f"[{law_id} - {article} - {law_title}]"
    return f"{prefix}\n\n{content}"


def chunk_article(
    text: str,
    *,
    article: str,
    law_title: str,
    law_id: str,
    section: str = "",
    source_file: str = "",
    jurisdiction: str = "ES",
    year: str = "",
    hierarchy_path: str = "",
) -> list[dict[str, Any]]:
    """Split *text* into one or more chunks obeying the token thresholds.

    * Articles whose token count is ≤ 800 → single chunk with
      ``chunk_type = "article"``.
    * Articles > 800 tokens → sub-chunks each ≤ 512 tokens with a
      50-token overlap; ``chunk_type = "sub_article"``.

    Each returned dict has ``content`` (raw article text, NOT prefixed) and
    ``metadata`` with all 9 required fields.
    """
    base_metadata = {
        "law_id": law_id,
        "law_title": law_title,
        "article": article,
        "section": section,
        "source_file": source_file,
        "jurisdiction": jurisdiction,
        "year": year,
        "hierarchy_path": hierarchy_path,
    }

    tokens = _ENC.encode(text)

    if len(tokens) <= _CHUNK_THRESHOLD:
        return [
            {
                "content": text,
                "metadata": {**base_metadata, "chunk_type": "article"},
            }
        ]

    # Sub-chunking with overlap
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(tokens):
        end = min(start + _SUB_CHUNK_SIZE, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = _ENC.decode(chunk_tokens)
        chunks.append(
            {
                "content": chunk_text,
                "metadata": {**base_metadata, "chunk_type": "sub_article"},
            }
        )
        if end == len(tokens):
            break
        # advance by (SUB_CHUNK_SIZE - OVERLAP) so next chunk overlaps by 50 tokens
        start += _SUB_CHUNK_SIZE - _OVERLAP

    return chunks


def parse_legal_structure(
    md_text: str,
    *,
    source_file: str,
    jurisdiction: str = "ES",
) -> list[dict[str, Any]]:
    """Parse *md_text* into article-level chunk dicts.

    Heading hierarchy assumed:
      H1 → law title   (sets current law; not an article by itself)
      H2 → section / título
      H3+ → article

    Year is extracted from the law title if a 4-digit year is present,
    otherwise defaults to empty string.
    """
    lines = md_text.splitlines()

    current_law_title = ""
    current_law_id = ""
    current_section = ""
    current_article = ""
    article_lines: list[str] = []
    chunks: list[dict[str, Any]] = []

    def _flush_article() -> None:
        nonlocal current_article, article_lines
        if not current_article or not article_lines:
            return
        text = "\n".join(article_lines).strip()
        if not text:
            article_lines = []
            current_article = ""
            return
        # Build hierarchy_path
        parts = [p for p in [current_law_id or current_law_title, current_section, current_article] if p]
        hp = " > ".join(parts)
        year = _extract_year(source_file, current_law_title)
        # Derive law_id: use filename base or law title
        law_id = current_law_id or _derive_law_id(source_file, current_law_title)

        article_chunks = chunk_article(
            text,
            article=current_article,
            law_title=current_law_title,
            law_id=law_id,
            section=current_section,
            source_file=source_file,
            jurisdiction=jurisdiction,
            year=year,
            hierarchy_path=hp,
        )
        chunks.extend(article_chunks)
        article_lines = []
        current_article = ""

    for line in lines:
        h1 = re.match(r"^# (.+)$", line)
        h2 = re.match(r"^## (.+)$", line)
        h3 = re.match(r"^#{3,} (.+)$", line)

        if h1:
            _flush_article()
            current_law_title = h1.group(1).strip()
            current_law_id = _derive_law_id(source_file, current_law_title)
            current_section = ""
            continue

        if h2:
            _flush_article()
            current_section = h2.group(1).strip()
            continue

        if h3:
            _flush_article()
            current_article = h3.group(1).strip()
            continue

        # Body line — belongs to current article
        if current_article:
            article_lines.append(line)

    _flush_article()  # flush the last article
    return chunks


def _derive_law_id(source_file: str, law_title: str) -> str:
    """Derive a short law identifier from the source filename or title."""
    stem = Path(source_file).stem
    if stem:
        return stem.upper()
    words = re.sub(r"[^A-Za-zÀ-ÿ\s]", "", law_title).split()
    stop = {"de", "del", "la", "las", "los", "el", "y", "e", "o", "u"}
    initials = "".join(w[0].upper() for w in words if w.lower() not in stop)
    return initials or "LAW"


# Matches any plausible year for Spanish legal documents (1000–2099).
# Covers 18xx (Bourbon-era laws), 19xx, and 20xx.
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")


def _extract_year(source_file: str, law_title: str) -> str:
    """Return the best 4-digit year string for a law, or empty string.

    Priority:
    1. Filename — BOE files embed the year as the third ``-``-separated
       segment, e.g. ``BOE-A-1835-2348`` → ``1835``.
    2. Law title — first 4-digit number in the plausible range 1000–2099.
    """
    stem = Path(source_file).stem  # e.g. "BOE-A-1835-2348"
    parts = stem.split("-")
    for part in parts:
        if _YEAR_RE.fullmatch(part):
            return part

    m = _YEAR_RE.search(law_title)
    return m.group(0) if m else ""


def generate_embeddings(cohere_client: Any, texts: list[str]) -> list[list[float]]:
    """Call Cohere embed API and return a list of float vectors.

    Sends texts in batches of ``_EMBED_BATCH_SIZE`` to stay within the trial
    rate limit (100 calls/min, 100k tokens/min). Retries each batch up to
    ``len(_EMBED_RETRY_DELAYS)`` times on 429 errors with exponential back-off.

    If the caller has wired the shared KeyPool singleton (via
    ``app.retrieval.embedder.get_cohere_pool()``), mid-batch key rotation is
    handled transparently by the pool.  This function stays pure (no direct
    pool coupling) so that unit tests can inject any mock client.

    Args:
        cohere_client: An initialised ``cohere.Client`` instance.
        texts: List of strings to embed.

    Returns:
        List of 1024-dimensional float vectors, one per input text.
    """
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i : i + _EMBED_BATCH_SIZE]
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0, *_EMBED_RETRY_DELAYS]):
            if delay:
                log.info(
                    "Rate limited — waiting %ds before retry (attempt %d/%d)...",
                    delay, attempt, len(_EMBED_RETRY_DELAYS),
                )
                time.sleep(delay)
            try:
                response = cohere_client.embed(
                    texts=batch,
                    model="embed-multilingual-v3.0",
                    input_type="search_document",
                )
                all_embeddings.extend(list(response.embeddings))
                last_exc = None
                break
            except Exception as exc:
                if "429" in str(exc) or "rate limit" in str(exc).lower():
                    last_exc = exc
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        # Polite pause between batches to stay well inside the rate limit
        if i + _EMBED_BATCH_SIZE < len(texts):
            time.sleep(_EMBED_INTER_BATCH_SLEEP)
    return all_embeddings


def upsert_documents(session_maker: Any, chunks: list[dict[str, Any]]) -> None:
    """Upsert *chunks* into the ``documents`` table using session.merge().

    Each chunk dict must have:
        - ``content``   : plain article text
        - ``embedding`` : list of 1024 floats
        - ``metadata``  : dict with at least the 9 required fields

    The ORM primary key is UUID; idempotency relies on the caller ensuring
    that the same ``(source_file, article)`` pair always maps to the same UUID
    (achieved by deriving the UUID deterministically from those two fields via
    ``uuid.uuid5``).

    ``tsvector`` is populated via a SQLAlchemy ``func.to_tsvector`` expression
    so that PostgreSQL computes it server-side.
    """
    import uuid as _uuid
    from uuid import NAMESPACE_URL as _NAMESPACE_URL
    from sqlalchemy import func, text
    from sqlalchemy.orm import Session

    from app.db.models import Document

    with session_maker() as session:
        for chunk in chunks:
            meta = chunk["metadata"]
            # Derive a stable UUID from (source_file, article) so re-runs merge
            stable_id = _uuid.uuid5(_NAMESPACE_URL, f"{meta['source_file']}|{meta['article']}")

            doc = Document(
                id=stable_id,
                content=chunk["content"],
                embedding=chunk["embedding"],
                metadata_=meta,
                tsvector=func.to_tsvector("spanish", chunk["content"]),
            )
            session.merge(doc)
        session.commit()


# ---------------------------------------------------------------------------
# CLI — clone, scan, ingest
# ---------------------------------------------------------------------------

def _clone_or_pull(repo_dir: Path) -> None:
    from git import Repo, InvalidGitRepositoryError, NoSuchPathError

    if repo_dir.exists():
        try:
            repo = Repo(str(repo_dir))
            log.info("Fetching %s ...", _REPO_URL)
            repo.remotes.origin.fetch()
        except (InvalidGitRepositoryError, NoSuchPathError):
            log.info("Cloning %s into %s ...", _REPO_URL, repo_dir)
            repo = Repo.clone_from(_REPO_URL, str(repo_dir))
    else:
        log.info("Cloning %s into %s ...", _REPO_URL, repo_dir)
        repo = Repo.clone_from(_REPO_URL, str(repo_dir))

    log.info("Checking out pinned commit %s ...", _REPO_COMMIT)
    repo.git.checkout(_REPO_COMMIT)


def _scan_md_files(repo_dir: Path) -> list[Path]:
    return sorted(repo_dir.rglob("*.md"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Thermia legal corpus ingestion pipeline.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate the documents table before ingesting.",
    )
    args = parser.parse_args(argv)

    # Load config (sets env vars from .env)
    import app.config  # noqa: F401 — side-effect: loads .env

    import cohere
    from sqlalchemy.orm import sessionmaker

    from app.db.connection import get_engine
    from app.retrieval.embedder import get_cohere_pool

    # Use the shared KeyPool singleton — do NOT read COHERE_API_KEY directly.
    # The pool reads COHERE_API_KEYS (JSON array) or falls back to legacy
    # COHERE_API_KEY with a WARN log. boot-fail-fast is handled by KeyPool.from_env.
    pool = get_cohere_pool()
    cohere_client = cohere.Client(pool.current())

    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    if args.reset:
        from sqlalchemy.orm import Session
        from app.db.models import Document
        with Session(engine) as session:
            session.query(Document).delete()
            session.commit()
        log.info("documents table truncated.")

    # Clone / pull the legal corpus
    _clone_or_pull(_REPO_DIR)

    md_files = _scan_md_files(_REPO_DIR)
    log.info("Found %d .md files.", len(md_files))

    total_inserted = 0
    failed_files: list[str] = []

    for md_path in md_files:
        rel_path = str(md_path.relative_to(_REPO_DIR))
        try:
            md_text = md_path.read_text(encoding="utf-8", errors="replace")
            chunks = parse_legal_structure(md_text, source_file=rel_path)
            if not chunks:
                log.info("  [skip] %s — no articles found.", rel_path)
                continue

            # Build embedding texts
            embed_texts = [
                build_embedding_text(
                    law_id=c["metadata"]["law_id"],
                    article=c["metadata"]["article"],
                    law_title=c["metadata"]["law_title"],
                    content=c["content"],
                )
                for c in chunks
            ]

            embeddings = generate_embeddings(cohere_client, embed_texts)
            for i, emb in enumerate(embeddings):
                chunks[i]["embedding"] = emb

            upsert_documents(session_factory, chunks)
            total_inserted += len(chunks)
            log.info("  [ok] %s — %d chunks upserted.", rel_path, len(chunks))

        except Exception as exc:  # noqa: BLE001
            log.error("  [error] %s — %s", rel_path, exc)
            failed_files.append(rel_path)
            continue

    log.info("Ingestion complete. Total chunks upserted: %d", total_inserted)
    if failed_files:
        log.error(
            "Ingestion finished with %d failed file(s):\n  %s",
            len(failed_files),
            "\n  ".join(failed_files),
        )

    # Stop SSH tunnel if present
    if hasattr(engine, "tunnel"):
        engine.tunnel.stop()

    if failed_files:
        sys.exit(1)


if __name__ == "__main__":
    main()
