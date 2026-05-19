"""Claude Code executor — the reference implementation.

In production, Claude Code's `Task()` primitive is invoked from the
orchestrator's `.md` prompt body. This Python adapter mirrors what the
orchestrator does so the conformance suite can exercise it and so a future
Python-driven orchestrator can call into the same logic.

For test scenarios where you don't want to actually invoke the LLM, inject
a `spawn_callable` that simulates the spawn (writes a fake output handoff).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

from .base import (
    Capabilities,
    SpawnResult,
    StageExecutor,
    EXECUTOR_VERSION,
    IsolationMode,
)


class ClaudeCodeExecutor(StageExecutor):
    """Adapter for Claude Code's `Task()` spawn mechanism."""

    name = "claude-code"
    version = "0.2.0"
    capabilities = Capabilities(
        max_concurrency=8,
        worktree_isolation=True,
        cancellation=True,
        target_tools=("claude", "claude-code"),
        spec_version=EXECUTOR_VERSION,
    )

    def __init__(
        self,
        repo_root: Path,
        *,
        spawn_callable: Optional[Callable[..., dict]] = None,
    ) -> None:
        """
        spawn_callable: Optional injection point for tests. When provided,
            the adapter calls this instead of attempting a real Claude Code
            spawn. The callable receives keyword args matching spawn()'s
            parameters and MUST write the output handoff to disk; it returns
            a dict with `tokens_in`, `tokens_out`, `status` (optional).

        In production (no spawn_callable), this adapter is invoked only
        indirectly — the orchestrator's .md prompt drives the Task() call
        and the result lands at the canonical handoff path. The Python
        adapter then validates that handoff.
        """
        self.repo_root = repo_root
        self._spawn_callable = spawn_callable

    def spawn(
        self,
        stage_name: str,
        input_handoff_path: Path,
        *,
        timeout_sec: Optional[int] = None,
        isolation: Optional[IsolationMode] = None,
    ) -> SpawnResult:
        start = time.monotonic()

        # 1. Compute canonical output handoff path
        run_handoff_dir = input_handoff_path.parent
        output_path = run_handoff_dir / f"{stage_name}.output.yaml"

        # 2. Invoke the spawn (or its test stand-in)
        info: dict = {}
        if self._spawn_callable is not None:
            try:
                info = self._spawn_callable(
                    stage_name=stage_name,
                    input_handoff_path=input_handoff_path,
                    output_handoff_path=output_path,
                    timeout_sec=timeout_sec,
                    isolation=isolation,
                ) or {}
            except TimeoutError:
                return SpawnResult(
                    status="timeout",
                    output_handoff_path=None,
                    wall_clock_sec=time.monotonic() - start,
                    error=f"spawn exceeded timeout_sec={timeout_sec}",
                )
            except Exception as exc:
                return SpawnResult(
                    status="failed",
                    output_handoff_path=None,
                    wall_clock_sec=time.monotonic() - start,
                    error=str(exc),
                )
        else:
            # In a real Claude Code session, the orchestrator's .md prompt
            # has already produced the output handoff at the canonical path
            # via the `Task()` call. This Python adapter's role is then
            # purely to validate after-the-fact. If the file is missing,
            # the orchestrator should not have invoked this adapter.
            if not output_path.exists():
                return SpawnResult(
                    status="failed",
                    output_handoff_path=None,
                    wall_clock_sec=time.monotonic() - start,
                    error=(
                        f"output handoff not found at {output_path}. "
                        "In Claude Code sessions, the orchestrator's Task() call "
                        "must write the output before this adapter is invoked."
                    ),
                )

        # 3. Validate output against the schema
        err = self._validate_output_handoff(stage_name, output_path, self.repo_root)
        if err:
            return SpawnResult(
                status="failed",
                output_handoff_path=output_path,
                wall_clock_sec=time.monotonic() - start,
                error=err,
            )

        # 4. Read the handoff to discover declared status + cost data
        import yaml
        handoff = yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
        declared_status = handoff.get("status", "complete")

        # If the spawn callable supplied tokens, prefer those; otherwise use
        # cost block from the handoff itself.
        cost = handoff.get("cost") or {}
        tokens_in = info.get("tokens_in") or int(cost.get("tokens_in") or 0)
        tokens_out = info.get("tokens_out") or int(cost.get("tokens_out") or 0)

        return SpawnResult(
            status=declared_status,
            output_handoff_path=output_path,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            wall_clock_sec=time.monotonic() - start,
            worktree_path=info.get("worktree_path"),
        )
