"""Scan failure types and the process exit codes they map to."""

from __future__ import annotations

from typing import Any

EXIT_BUDGET_EXCEEDED = 2
EXIT_AGENT_NO_SUBMIT = 3
EXIT_PREFLIGHT_FAILED = 4


class AgentDidNotSubmitError(RuntimeError):
    """The model stopped without calling submit_findings, even after a re-prompt."""


class PreflightFailedError(RuntimeError):
    """An environment check failed before any LLM budget was spent."""

    def __init__(self, message: str, result: Any = None) -> None:
        super().__init__(message)
        self.result = result


class StrictCoverageError(RuntimeError):
    """STRICT_COVERAGE is on and the resource cap left resources unanalysed."""
