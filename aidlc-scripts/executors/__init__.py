"""AIDLC executor adapters — implements the `executor.v1.md` contract.

See `.aidlc-orchestrator/contracts/executor.v1.md` for the interface
specification. Adapters live in this package; the active adapter is selected
at install time via `aidlc-scripts/executors/registry.yaml`.
"""

from .base import (
    StageExecutor,
    SpawnResult,
    SpawnStatus,
    EXECUTOR_VERSION,
    ExecutorUnavailableError,
    Capabilities,
)
from .claude_code_executor import ClaudeCodeExecutor
from .opencode_executor import OpenCodeExecutor

__all__ = [
    "StageExecutor",
    "SpawnResult",
    "SpawnStatus",
    "EXECUTOR_VERSION",
    "ExecutorUnavailableError",
    "Capabilities",
    "ClaudeCodeExecutor",
    "OpenCodeExecutor",
]
