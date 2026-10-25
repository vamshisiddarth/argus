"""Results of the checks run before a scan spends any LLM budget."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CheckStatus = Literal["ok", "info", "warn", "fail"]


@dataclass(frozen=True)
class PreflightCheck:
    code: str
    status: CheckStatus
    message: str
    fix: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class PreflightResult:
    account_id: str | None = None
    checks: list[PreflightCheck] = field(default_factory=list)
    skipped: bool = False

    @property
    def failed(self) -> list[PreflightCheck]:
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warnings(self) -> list[PreflightCheck]:
        return [c for c in self.checks if c.status == "warn"]

    def describe_failures(self) -> str:
        lines = []
        for c in self.failed:
            lines.append(f"{c.code}: {c.message}" + (f" Fix: {c.fix}" if c.fix else ""))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "skipped": self.skipped,
            "checks": [c.to_dict() for c in self.checks],
        }

    @classmethod
    def skipped_result(cls, account_id: str | None = None) -> PreflightResult:
        return cls(account_id=account_id, skipped=True)
