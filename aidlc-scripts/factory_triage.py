#!/usr/bin/env python3
"""factory_triage.py — Complexity classifier for AIDLC Orchestrator.

Two modes:

1. PREFILTER (default): quick regex check for truly trivial work (typo, README,
   config change). If trivial, exits 0 (TINY, FAST_PATH). Otherwise exits 10
   to signal "needs LLM classification".

2. PROMPT & APPLY: output a structured classification prompt for the LLM, and
   map the LLM's JSON response to a pipeline tier.

Usage
-----
    factory_triage.py --prefilter "<user-request>"
        Exit: 0 = TINY (trivial), 10 = needs LLM classification

    factory_triage.py --prompt "<user-request>"
        Print the structured classification prompt (for orchestrator to send to LLM).

    factory_triage.py --apply <classification.json>
        Read structured classification JSON from file/stdin, print tier + pipeline.
        Exit: 1 = SMALL, 2 = MEDIUM, 3 = LARGE
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TRIVIAL_PATTERNS = re.compile(
    r"^(fix|correct|update|change|remove|add|rename|delete)\s+"
    r"(a\s+|an\s+|the\s+)?"
    r"(typo|readme|comment|docs?|config|gitignore|editor.?config|license)",
    re.IGNORECASE,
)

_CLASSIFICATION_PROMPT = """You are a software engineering complexity triage engine.

Your job is NOT to classify the request directly into a tier.
Instead, you must extract structured complexity attributes that will be used by a deterministic policy engine.

The input can be in ANY language.

---

INPUT:
{request}

---

OUTPUT (STRICT JSON):
Return ONLY valid JSON. No explanations. No markdown.

{{
  "intent": "create | modify | debug | refactor | migrate | investigate | unknown",
  "scope": "single_file | single_module | multi_module | cross_service | system_wide",
  "risk": "low | medium | high | critical",
  "architecture_impact": "none | low | medium | high",
  "security_relevance": "none | low | medium | high",
  "external_dependencies": ["list of APIs/services mentioned or implied"],
  "data_layer_impact": "none | low | medium | high",
  "coordination_required": true | false,
  "ambiguity": "low | medium | high",
  "estimated_affected_components": "1-2 | 3-5 | 6-10 | 10+",
  "language_detected": "auto",
  "notes": "short neutral description of reasoning signals (no chain-of-thought)"
}}

---

RULES:

1. Do NOT classify into tiers (TINY/SMALL/MEDIUM/LARGE). That is handled externally.
2. Focus on semantic meaning, not keywords.
3. Be robust to all languages (Spanish, English, French, German, etc.).
4. Infer implicit complexity even if not explicitly stated.
5. If uncertain, choose higher risk rather than lower.
6. Treat these as high-risk signals:
   - authentication / authorization / identity
   - payments / billing
   - distributed systems
   - data migrations
   - concurrency / async / queues
   - infrastructure / deployment
   - microservices / system design
7. "scope" is about blast radius, not number of words.
8. "coordination_required" = true if multiple subsystems or roles would be needed in a real engineering team.
9. "notes" must be short and factual, no reasoning chains.

---

EXAMPLES OF INTERPRETATION:

- "add login with google" -> security_relevance: medium/high, scope: multi_module
- "fix typo in README" -> scope: single_file, risk: low
- "migrate monolith to microservices" -> scope: system_wide, architecture_impact: high

---

OUTPUT MUST BE VALID JSON ONLY.
"""


def _score_to_scope_weight(scope: str) -> int:
    mapping = {
        "single_file": 0,
        "single_module": 1,
        "multi_module": 2,
        "cross_service": 3,
        "system_wide": 4,
    }
    return mapping.get(scope, 1)


def _score_to_impact(level: str) -> int:
    mapping = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    return mapping.get(level, 1)


def _components_to_score(count: str) -> int:
    mapping = {"1-2": 0, "3-5": 1, "6-10": 2, "10+": 3}
    return mapping.get(count, 1)


def classification_to_tier(data: dict) -> tuple[str, str, int]:
    """Map structured LLM classification to pipeline tier.

    Weighted scoring across multiple dimensions. Only truly trivial work
    (caught by prefilter) qualifies for TINY — everything else goes through
    LLM classification and maps to SMALL+.
    """
    score = 0
    score += _score_to_scope_weight(data.get("scope", "single_module"))
    score += _score_to_impact(data.get("architecture_impact", "none"))
    score += _score_to_impact(data.get("security_relevance", "none"))
    score += _score_to_impact(data.get("risk", "low"))
    score += _score_to_impact(data.get("data_layer_impact", "none"))
    score += _components_to_score(data.get("estimated_affected_components", "1-2"))
    if data.get("coordination_required"):
        score += 2
    score += _score_to_impact(data.get("ambiguity", "low"))

    if score <= 6:
        return "SMALL", "full", 1
    if score <= 13:
        return "MEDIUM", "full", 2
    return "LARGE", "full", 3


def is_trivial(text: str) -> bool:
    """Check if the request is truly trivial (typo, README, config, rename)."""
    return bool(_TRIVIAL_PATTERNS.match(text.strip()))


def cmd_prefilter(args: argparse.Namespace) -> None:
    if is_trivial(args.request):
        result = {"tier": "TINY", "score": 0, "pipeline": "fast"}
        print(json.dumps(result))
        sys.exit(0)
    # Not trivial — orchestrator should use LLM classification
    result = {"tier": "UNKNOWN", "score": -1, "pipeline": "classify"}
    print(json.dumps(result))
    sys.exit(10)


def cmd_prompt(args: argparse.Namespace) -> None:
    """Print the LLM classification prompt with the request injected."""
    print(_CLASSIFICATION_PROMPT.format(request=args.request))


def cmd_apply(args: argparse.Namespace) -> None:
    source = args.classification
    if source == "-":
        data = json.loads(sys.stdin.read())
    else:
        data = json.loads(Path(source).read_text())
    tier, pipeline, exit_code = classification_to_tier(data)
    result = {
        "tier": tier,
        "score": None,
        "pipeline": pipeline,
        "classification": data,
    }
    print(json.dumps(result, indent=2))
    sys.exit(exit_code)


def main() -> None:
    p = argparse.ArgumentParser(
        description="AIDLC Orchestrator — Complexity Triage"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("prefilter",
        help="Quick TINY check for trivial requests (typo, README, config)")
    p_pre.add_argument("request", help="User request text")
    p_pre.set_defaults(func=cmd_prefilter)

    p_pr = sub.add_parser("prompt",
        help="Print LLM classification prompt (for orchestrator to use)")
    p_pr.add_argument("request", help="User request text")
    p_pr.set_defaults(func=cmd_prompt)

    p_ap = sub.add_parser("apply",
        help="Map LLM classification JSON to pipeline tier")
    p_ap.add_argument("classification", nargs="?",
        default="-", help="Path to JSON file, or '-' for stdin")
    p_ap.set_defaults(func=cmd_apply)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
