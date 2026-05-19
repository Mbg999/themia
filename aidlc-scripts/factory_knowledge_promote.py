#!/usr/bin/env python3
"""factory_knowledge_promote.py — Promote recurring patterns to shared corpus.

When the same pattern (kind=pattern, decision, antipattern, lesson) recurs
across ≥3 distinct projects with cosine similarity ≥ 0.85, promote it to the
shared topic-key namespace `aidlc/_shared/<kind>/<slug>`.

Promotion is provenance-tracked: the promoted observation carries pointers
back to each source observation by sync_id and project.

Data flow (current implementation — no live engram coupling):

    1. User exports observations from engram as JSONL (one observation per line).
       Each line must include at minimum:
           {"sync_id", "project", "kind", "title", "body", "tags"?, "topic_key"?}
    2. This script consumes the JSONL, clusters by similarity, and emits
       promotion records as JSONL.
    3. User applies the promotions to engram via mem_save into the
       aidlc/_shared/<kind>/<slug> namespace.

Similarity is computed as cosine similarity over the bag-of-words TF
vectorization of `title + body`. Anchor-key terms (project names, run IDs)
are stripped to avoid spurious clustering by project.

Usage:
    python3 aidlc-scripts/factory_knowledge_promote.py \\
        --observations observations.jsonl \\
        --out promotions.jsonl

Tuning:
    --min-projects N         (default 3) minimum distinct projects required
    --similarity-threshold X (default 0.85) cosine similarity floor
    --dry-run                Print candidate clusters without writing the file

Exit codes:
    0  promotions emitted (or none — both are success)
    2  usage error / unreadable input
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ORCHESTRATOR_VERSION = "0.2.0"

# Strip common anchor terms that would cluster things by project, not pattern.
STOP_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}[\w-]*\b"),       # run-id-like
    re.compile(r"\b[a-f0-9]{8,}\b"),                 # hashes / sync ids
    re.compile(r"`[^`]+`"),                          # backtick code refs (file paths, names)
    re.compile(r"https?://\S+"),                     # URLs
]
WORD_RE = re.compile(r"[a-z][a-z0-9-]{2,}")


def _die(msg: str, code: int = 2) -> None:
    print(f"factory_knowledge_promote: error: {msg}", file=sys.stderr)
    sys.exit(code)


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    for sp in STOP_PATTERNS:
        text = sp.sub(" ", text)
    return WORD_RE.findall(text)


def _tf(tokens: list[str]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    if not counts:
        return {}
    inv_n = 1.0 / len(tokens)
    return {k: v * inv_n for k, v in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_observations(path: Path) -> list[dict]:
    if not path.exists():
        _die(f"observations file not found: {path}")
    out: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError as exc:
            _die(f"line {i}: invalid JSON: {exc}")
        # Required fields
        for f in ("sync_id", "project", "kind", "title", "body"):
            if f not in d:
                _die(f"line {i}: missing required field '{f}'")
        d.setdefault("topic_key", "")
        d.setdefault("tags", [])
        out.append(d)
    return out


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "untitled"


def cluster(
    obs: list[dict],
    *,
    min_projects: int,
    similarity_threshold: float,
) -> list[dict]:
    """Return promotion candidates.

    Greedy single-linkage clustering by kind: take an unassigned seed, pull
    in every observation whose similarity to the seed ≥ threshold (within
    same kind), keep cluster if it spans ≥ min_projects distinct projects.
    """
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for o in obs:
        by_kind[o["kind"]].append(o)

    clusters: list[dict] = []
    for kind, items in by_kind.items():
        # Precompute TF vectors
        for it in items:
            it["_tf"] = _tf(_tokenize(it["title"] + " " + it["body"]))
        assigned: set[int] = set()
        for i, seed in enumerate(items):
            if i in assigned:
                continue
            cluster_ids = [i]
            for j in range(i + 1, len(items)):
                if j in assigned:
                    continue
                if _cosine(seed["_tf"], items[j]["_tf"]) >= similarity_threshold:
                    cluster_ids.append(j)
            members = [items[k] for k in cluster_ids]
            projects = {m["project"] for m in members}
            if len(projects) >= min_projects:
                # Build a promotion record
                # Use the longest title as the canonical
                canonical = max(members, key=lambda m: len(m["title"]))
                slug = _slugify(canonical["title"])
                clusters.append({
                    "topic_key": f"aidlc/_shared/{kind}/{slug}",
                    "kind": kind,
                    "title": canonical["title"],
                    "body": canonical["body"],
                    "tags": sorted({t for m in members for t in (m.get("tags") or [])}),
                    "projects_observed_in": sorted(projects),
                    "provenance": [
                        {"sync_id": m["sync_id"], "project": m["project"],
                         "title": m["title"]}
                        for m in members
                    ],
                    "member_count": len(members),
                })
                for k in cluster_ids:
                    assigned.add(k)

    # Strip internal _tf keys before returning
    for it in obs:
        it.pop("_tf", None)
    return clusters


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="factory_knowledge_promote.py",
        description="Promote recurring patterns from per-project to shared corpus.",
    )
    parser.add_argument("--observations", required=True,
                        help="Path to JSONL of engram observations to consider")
    parser.add_argument("--out", default=None,
                        help="Output JSONL of promotion records (default: stdout)")
    parser.add_argument("--min-projects", type=int, default=3)
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    obs_path = Path(args.observations).resolve()
    obs = _load_observations(obs_path)

    promotions = cluster(
        obs,
        min_projects=args.min_projects,
        similarity_threshold=args.similarity_threshold,
    )

    if args.dry_run:
        print(f"# dry-run: {len(promotions)} promotion candidate(s) found")
        for p in promotions:
            print(f"\n## {p['topic_key']}  ({p['member_count']} members across "
                  f"{len(p['projects_observed_in'])} projects)")
            print(f"  title: {p['title']}")
            print(f"  projects: {', '.join(p['projects_observed_in'])}")
        return

    out_lines = [json.dumps(p) for p in promotions]
    output = "\n".join(out_lines) + ("\n" if out_lines else "")
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"factory_knowledge_promote: wrote {len(promotions)} promotion(s) to {args.out}",
              file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
