"""StageExecutor — base contract from .aidlc-orchestrator/contracts/executor.v1.md.

Adapters MUST subclass StageExecutor and implement `spawn()` plus the
metadata properties (`name`, `version`, `capabilities`). Optional methods
(`cancel`, `health_check`) have default no-op implementations.

The conformance test suite at `tests/test_executor_conformance.py` exercises
every registered adapter against the v1 contract.
"""

from __future__ import annotations

import abc
import dataclasses
from pathlib import Path
from typing import Optional, Literal

EXECUTOR_VERSION = "v1"

SpawnStatus = Literal[
    "complete", "blocked", "failed", "needs_human",
    "timeout", "cancelled", "unsupported",
]

IsolationMode = Literal["worktree"]


class ExecutorUnavailableError(RuntimeError):
    """Raised when an executor cannot satisfy the requested spawn — e.g.,
    the underlying SDK is not installed, credentials are missing, or the
    isolation mode is not supported. Callers should catch this and either
    fall back to another executor or fail-fast with a clear message.
    """


@dataclasses.dataclass(frozen=True)
class Capabilities:
    """Adapter capability declaration. Used by the orchestrator to decide
    fallback behavior (e.g., sequential mode if `max_concurrency < 4`)."""

    max_concurrency: int
    worktree_isolation: bool
    cancellation: bool
    target_tools: tuple[str, ...]
    spec_version: str = EXECUTOR_VERSION


@dataclasses.dataclass(frozen=True)
class SpawnResult:
    """Return value of StageExecutor.spawn().

    Mirrors the SpawnResult shape from executor.v1.md §3.
    """

    status: SpawnStatus
    output_handoff_path: Optional[Path]
    tokens_in: int = 0
    tokens_out: int = 0
    wall_clock_sec: float = 0.0
    worktree_path: Optional[Path] = None
    error: Optional[str] = None
    spawn_id: Optional[str] = None


class StageExecutor(abc.ABC):
    """Abstract base for agentic-tool spawn adapters.

    Subclasses MUST set `name` and `capabilities` class attributes, and
    implement `spawn()`. See executor.v1.md for full semantics.
    """

    # Metadata — subclasses MUST override.
    name: str = "unset"
    version: str = "0.0.0"
    capabilities: Capabilities = Capabilities(
        max_concurrency=1,
        worktree_isolation=False,
        cancellation=False,
        target_tools=(),
    )

    # -- Required methods --

    @abc.abstractmethod
    def spawn(
        self,
        stage_name: str,
        input_handoff_path: Path,
        *,
        timeout_sec: Optional[int] = None,
        isolation: Optional[IsolationMode] = None,
    ) -> SpawnResult:
        """Spawn one stage. See executor.v1.md §3 for invariants.

        MUST validate output against `<stage>.output.v1.json` before returning.
        MUST emit `tokens_in`, `tokens_out`, `wall_clock_sec` on the result.
        MUST NOT mutate manifest.yaml or timeline.jsonl.
        """

    # -- Optional methods (sensible defaults) --

    def cancel(self, spawn_id: str) -> SpawnResult:
        """Cooperative cancellation. Default impl returns `unsupported`."""
        return SpawnResult(
            status="unsupported",
            output_handoff_path=None,
            error=f"{self.name} adapter does not support cancellation",
            spawn_id=spawn_id,
        )

    def health_check(self) -> bool:
        """Return True if the adapter is operational. Default: True."""
        return True

    # -- Conformance helpers shared across implementations --

    def _validate_output_handoff(
        self,
        stage_name: str,
        output_handoff_path: Path,
        repo_root: Path,
    ) -> Optional[str]:
        """Run factory_validate.py against the output handoff.

        Returns None on success, or a string error on failure.
        """
        import subprocess
        import sys
        contract = (
            repo_root
            / ".aidlc-orchestrator"
            / "contracts"
            / f"{stage_name}.output.v1.json"
        )
        # Reviewers share a contract — adapt
        if stage_name.startswith("reviewer-") and not contract.exists():
            contract = (
                repo_root
                / ".aidlc-orchestrator"
                / "contracts"
                / "reviewer.output.v1.json"
            )
        if not contract.exists():
            return f"contract missing for {stage_name}: {contract}"
        if not output_handoff_path.exists():
            return f"output handoff missing: {output_handoff_path}"
        validate_py = repo_root / "aidlc-scripts" / "factory_validate.py"
        result = subprocess.run(
            [sys.executable, str(validate_py), str(contract), str(output_handoff_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return f"schema validation failed: {result.stderr.strip() or result.stdout.strip()}"
        return None
