"""OpenCode executor — DOCUMENTED STUB.

This adapter satisfies the executor.v1.md interface shape, registers with
`registry.yaml`, and is discoverable by `install_aidlc.py --tool opencode`.

The actual OpenCode SDK integration is **not yet implemented**. `spawn()`
raises `NotImplementedError` with a clear pointer to what's needed.

To complete this adapter:

1. Add the OpenCode SDK to `requirements.txt`:
       opencode-sdk>=X.Y  (replace with real package name + version)

2. Import the SDK at the top of `_invoke_opencode_task`.

3. Implement `_invoke_opencode_task` so that:
   a. The OpenCode agent runs against the stage agent prompt at
      `.opencode/agents/<stage_name>.md` (or `.claude/agents/stage/<stage_name>.md`
      if symlinked; the install script handles this).
   b. The agent receives `input_handoff_path` and produces
      `output_handoff_path` matching the canonical filename.
   c. Return token counts and any worktree-related metadata.

4. Implement `cancel()` using the SDK's cancellation API (likely a
   subprocess.terminate or SDK-specific cancel signal).

5. Run `pytest tests/test_executor_conformance.py` — the suite is
   parameterized across registered executors. The OpenCode rows will go
   from `skipped` to `passing` once `_invoke_opencode_task` is real.

Until step 5 is green, `health_check()` returns False so the orchestrator
falls back to the legacy single-agent flow instead of attempting spawns
that would fail.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from .base import (
    Capabilities,
    SpawnResult,
    StageExecutor,
    EXECUTOR_VERSION,
    IsolationMode,
    ExecutorUnavailableError,
)


class OpenCodeExecutor(StageExecutor):
    """Adapter for OpenCode's agent spawn mechanism — STUB."""

    name = "opencode"
    version = "0.1.0-stub"
    capabilities = Capabilities(
        max_concurrency=4,
        worktree_isolation=True,
        cancellation=True,
        target_tools=("opencode",),
        spec_version=EXECUTOR_VERSION,
    )

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def health_check(self) -> bool:
        """Returns False until `_invoke_opencode_task` is implemented.

        When the OpenCode SDK is installed and integrated, this should
        attempt an SDK-side ping and return True only on success.
        """
        return False

    def spawn(
        self,
        stage_name: str,
        input_handoff_path: Path,
        *,
        timeout_sec: Optional[int] = None,
        isolation: Optional[IsolationMode] = None,
    ) -> SpawnResult:
        start = time.monotonic()
        try:
            output_path = self._invoke_opencode_task(
                stage_name=stage_name,
                input_handoff_path=input_handoff_path,
                timeout_sec=timeout_sec,
                isolation=isolation,
            )
        except NotImplementedError as exc:
            return SpawnResult(
                status="unsupported",
                output_handoff_path=None,
                wall_clock_sec=time.monotonic() - start,
                error=str(exc),
            )

        err = self._validate_output_handoff(stage_name, output_path, self.repo_root)
        if err:
            return SpawnResult(
                status="failed",
                output_handoff_path=output_path,
                wall_clock_sec=time.monotonic() - start,
                error=err,
            )

        import yaml
        handoff = yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
        cost = handoff.get("cost") or {}
        return SpawnResult(
            status=handoff.get("status", "complete"),
            output_handoff_path=output_path,
            tokens_in=int(cost.get("tokens_in") or 0),
            tokens_out=int(cost.get("tokens_out") or 0),
            wall_clock_sec=time.monotonic() - start,
        )

    # -- internal --

    def _invoke_opencode_task(
        self,
        *,
        stage_name: str,
        input_handoff_path: Path,
        timeout_sec: Optional[int],
        isolation: Optional[IsolationMode],
    ) -> Path:
        """Implement this when integrating the OpenCode SDK.

        Expected behavior:
        1. Load the OpenCode SDK client.
        2. Submit a job referencing `.opencode/agents/<stage_name>.md` (or the
           Claude Code equivalent if the symlink-install option was chosen).
        3. Pass `input_handoff_path` as the agent's input.
        4. Honor `timeout_sec` and `isolation` per executor.v1.md §3 and §9.
        5. Return the path to the produced output handoff.

        Until implemented:
        """
        raise NotImplementedError(
            "OpenCodeExecutor._invoke_opencode_task is a stub. "
            "Implement OpenCode SDK integration here — see the module "
            "docstring of opencode_executor.py for the integration checklist."
        )
