"""
Thermia ingestion pipeline CLI.

Clones https://github.com/legalize-dev/legalize-es, scans all .md files,
parses Spanish legal structure (H1=law, H2=title/section, H3+=article),
chunks each article, generates embeddings via Ollama (bge-m3 model), and
upserts into the `documents` table idempotently.

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

import ollama as _ollama
import tiktoken

# ---------------------------------------------------------------------------
# Make `thermia-back/` importable when the script is invoked directly
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Deferred heavy imports so unit-tests can import pure functions without
# triggering the DB / Ollama imports (which require real env vars).

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

# Ollama embedding configuration
_EMBED_BATCH_SIZE = 50    # max texts per embed() call
_EMBED_RETRY_COUNT = 2    # retries after initial attempt
_EMBED_RETRY_DELAY = 5.0  # seconds between retries
_EMBED_INTER_BATCH_SLEEP = 1.0  # polite pause between batches (seconds)

# Tiktoken encoding — cl100k_base is compatible with multilingual models
_ENC = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Pure functions (importable without real DB / Ollama)
# ---------------------------------------------------------------------------


def _count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


def build_embedding_text(*, law_id: str, article: str, law_title: str, content: str) -> str:
    """Return the prefixed text sent to the embedding model.

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
                "metadata": {**base_metadata, "chunk_type": "article", "chunk_index": 0},
            }
        ]

    # Sub-chunking with overlap
    chunks: list[dict[str, Any]] = []
    chunk_index = 0
    start = 0
    while start < len(tokens):
        end = min(start + _SUB_CHUNK_SIZE, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = _ENC.decode(chunk_tokens)
        chunks.append(
            {
                "content": chunk_text,
                "metadata": {**base_metadata, "chunk_type": "sub_article", "chunk_index": chunk_index},
            }
        )
        chunk_index += 1
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

    YAML frontmatter (--- blocks) is stripped before parsing. Extracted fields
    (status, legal_rank, country/jurisdiction) are added to every chunk's
    metadata; the full frontmatter dict is stored as ``source_metadata``.

    Year is extracted from the law title if a 4-digit year is present,
    otherwise defaults to empty string.
    """
    from app.ingestion.metadata_helpers import (
        parse_frontmatter, extract_legal_rank, normalize_status, derive_eli,
    )

    # Strip frontmatter and extract legal metadata before parsing body text.
    frontmatter, body_text = parse_frontmatter(md_text)
    fm_legal_rank = extract_legal_rank(frontmatter, frontmatter.get("title", ""))
    fm_status = normalize_status(frontmatter.get("status"))
    fm_jurisdiction = (frontmatter.get("country") or jurisdiction).upper()
    fm_eli = derive_eli(frontmatter)
    fm_source_metadata: dict | None = frontmatter if frontmatter else None

    lines = body_text.splitlines()

    current_law_title = ""
    current_law_id = ""
    current_section = ""
    current_article = ""
    article_lines: list[str] = []
    chunks: list[dict[str, Any]] = []

    def _flush_article() -> None:
        nonlocal current_article, article_lines
        # For H1-only documents (no H3 headings) use the law title as the article name.
        effective_article = current_article or current_law_title
        if not effective_article or not article_lines:
            return
        text = "\n".join(article_lines).strip()
        if not text:
            article_lines = []
            current_article = ""
            return
        # Build hierarchy_path
        parts = [p for p in [current_law_id or current_law_title, current_section, effective_article] if p]
        hp = " > ".join(parts)
        year = _extract_year(source_file, current_law_title)
        # Derive law_id: use filename base or law title
        law_id = current_law_id or _derive_law_id(source_file, current_law_title)

        article_chunks = chunk_article(
            text,
            article=effective_article,
            law_title=current_law_title,
            law_id=law_id,
            section=current_section,
            source_file=source_file,
            jurisdiction=fm_jurisdiction,
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

        # Body line — collect under current article or law body (H1-only docs have no H3).
        # Lines before the first H1 (e.g. raw frontmatter) are ignored via current_law_title guard.
        if current_law_title:
            article_lines.append(line)

    _flush_article()  # flush the last article

    # If frontmatter rank was empty, try again with the H1 title parsed from body.
    effective_rank = fm_legal_rank or extract_legal_rank(frontmatter, current_law_title)

    # Enrich every chunk with the frontmatter-derived fields.
    for chunk in chunks:
        chunk["metadata"]["legal_rank"] = effective_rank
        chunk["metadata"]["status"] = fm_status
        if fm_eli:
            chunk["metadata"]["eli"] = fm_eli
        chunk["source_metadata"] = fm_source_metadata

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


def _validate_ollama_host(host: str) -> None:
    """Raise RuntimeError if a non-localhost host does not use https://."""
    from urllib.parse import urlparse
    parsed = urlparse(host)
    hostname = parsed.hostname or ""
    is_local = hostname in ("localhost", "127.0.0.1", "::1") or hostname.startswith("127.")
    if not is_local and parsed.scheme != "https":
        raise RuntimeError(
            f"OLLAMA_HOST must use https:// for non-localhost targets, got: {host!r}"
        )


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Call Ollama embed API and return a list of float vectors.

    Sends texts in batches of ``_EMBED_BATCH_SIZE``. Retries each batch up to
    ``_EMBED_RETRY_COUNT`` times on transient errors with a fixed delay.

    Creates an explicit ``ollama.Client`` from ``OLLAMA_HOST`` (validated) so
    that the call is not subject to the package-level singleton which may be
    initialised before dotenv is loaded.

    Args:
        texts: List of strings to embed.

    Returns:
        List of 1024-dimensional float vectors, one per input text.
    """
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    _validate_ollama_host(host)
    client = _ollama.Client(host=host, timeout=30.0)

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i : i + _EMBED_BATCH_SIZE]
        last_exc: Exception | None = None
        for attempt in range(1 + _EMBED_RETRY_COUNT):
            try:
                response = client.embed(model="bge-m3", input=batch)
                all_embeddings.extend(response["embeddings"])
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < _EMBED_RETRY_COUNT:
                    log.info(
                        "Embedding attempt %d failed — retrying in %.0fs ...",
                        attempt + 1,
                        _EMBED_RETRY_DELAY,
                    )
                    time.sleep(_EMBED_RETRY_DELAY)
                else:
                    log.error(
                        "Embedding batch failed after %d attempts: %s",
                        _EMBED_RETRY_COUNT + 1,
                        type(exc).__name__,
                    )
        if last_exc is not None:
            raise last_exc
        if i + _EMBED_BATCH_SIZE < len(texts):
            time.sleep(_EMBED_INTER_BATCH_SLEEP)
    return all_embeddings


def upsert_documents(session_maker: Any, chunks: list[dict[str, Any]]) -> None:
    """Upsert *chunks* into the ``documents`` table using session.merge().

    Each chunk dict must have:
        - ``content``        : plain article text
        - ``embedding``      : list of 1024 floats
        - ``metadata``       : dict with at least the 9 required fields
        - ``source_metadata``: optional dict of raw frontmatter fields (or None)

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
            chunk_index = meta.get("chunk_index", 0)
            # Derive a stable UUID from (source_file, article, chunk_index) so re-runs merge.
            # chunk_index disambiguates sub-chunks of the same article without shifting
            # when unrelated articles are added earlier in the same file.
            stable_id = _uuid.uuid5(_NAMESPACE_URL, f"{meta['source_file']}|{meta['article']}|{chunk_index}")

            doc = Document(
                id=stable_id,
                content=chunk["content"],
                metadata_=meta,
                **({} if chunk["embedding"] is None else {"embedding": chunk["embedding"]}),
                tsvector=func.to_tsvector("spanish", chunk["content"]),
                status=meta.get("status", ""),
                legal_rank=meta.get("legal_rank", ""),
                jurisdiction=meta.get("jurisdiction", "ES"),
                source_metadata_=chunk.get("source_metadata"),
            )
            session.merge(doc)
        session.commit()


# ---------------------------------------------------------------------------
# CLI — clone, scan, ingest
# ---------------------------------------------------------------------------

def _clone_or_pull(repo_dir: Path) -> None:
    import fcntl
    from git import Repo, InvalidGitRepositoryError, NoSuchPathError

    lock_path = Path(str(repo_dir) + ".lock")
    with open(lock_path, "w") as _lock:
        fcntl.flock(_lock, fcntl.LOCK_EX)

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


def _parse_shard(value: str) -> tuple[int, int]:
    """Parse 'INDEX/TOTAL' shard spec, e.g. '0/2' or '1/2'."""
    try:
        idx_str, total_str = value.split("/")
        idx, total = int(idx_str), int(total_str)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError("--shard must be INDEX/TOTAL, e.g. 0/2")
    if total < 1:
        raise argparse.ArgumentTypeError("TOTAL must be >= 1")
    if not (0 <= idx < total):
        raise argparse.ArgumentTypeError(f"INDEX must be 0..{total - 1}, got {idx}")
    return idx, total


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Thermia legal corpus ingestion pipeline.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate the documents table before ingesting.",
    )
    parser.add_argument(
        "--shard",
        metavar="INDEX/TOTAL",
        type=_parse_shard,
        default=None,
        help=(
            "Process only a round-robin slice of the file list. "
            "Run two instances with --shard 0/2 and --shard 1/2 to parallelise ingestion."
        ),
    )
    args = parser.parse_args(argv)

    # Load config (sets env vars from .env)
    import app.config  # noqa: F401 — side-effect: loads .env

    from sqlalchemy.orm import sessionmaker

    from app.db.connection import get_engine

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

    if args.shard is not None:
        shard_idx, shard_total = args.shard
        md_files = md_files[shard_idx::shard_total]
        log.info("Shard %d/%d — processing %d file(s).", shard_idx, shard_total, len(md_files))

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

            embeddings = generate_embeddings(embed_texts)
            for i, emb in enumerate(embeddings):
                chunks[i]["embedding"] = emb

            upsert_documents(session_factory, chunks)
            total_inserted += len(chunks)
            log.info("  [ok] %s — %d chunks upserted.", rel_path, len(chunks))

        except Exception as exc:  # noqa: BLE001
            log.error("  [error] %s — %s", rel_path, type(exc).__name__)
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
