"""Scan provenance collected from AgentLoop runs and handed to build_report()."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.agent.loop import AgentLoop
from core.errors import StrictCoverageError
from core.models.coverage import Coverage
from core.models.preflight import PreflightResult


@dataclass
class ScanMeta:
    coverages: list[Coverage] = field(default_factory=list)
    scan_window: dict[str, Any] | None = None
    preflights: list[PreflightResult] = field(default_factory=list)

    def add_loop(self, loop: AgentLoop) -> None:
        if isinstance(loop.coverage, Coverage):
            self.coverages.append(loop.coverage)
        window = getattr(loop, "scan_window", None)
        if self.scan_window is None and isinstance(window, dict):
            self.scan_window = window

    def preflight_dict(self) -> dict[str, Any] | None:
        if not self.preflights:
            return None
        return {
            "skipped": all(p.skipped for p in self.preflights),
            "accounts": [p.to_dict() for p in self.preflights],
        }

    def preflight_summary(self) -> dict[str, Any] | None:
        if not self.preflights:
            return None
        return {
            "skipped": all(p.skipped for p in self.preflights),
            "warnings": [
                f"{c.code}: {c.message}" for p in self.preflights for c in p.warnings
            ],
        }

    @property
    def coverage(self) -> Coverage | None:
        return Coverage.merge(self.coverages) if self.coverages else None

    def coverage_dict(self) -> dict[str, Any] | None:
        cov = self.coverage
        return cov.to_dict() if cov else None

    def enforce_strict(self, strict: bool) -> None:
        cov = self.coverage
        if not strict or cov is None:
            return
        if cov.truncated:
            raise StrictCoverageError(
                f"Coverage truncated: analysed {cov.analysed} of {cov.discovered} "
                f"resources. Raise MAX_RESOURCES_PER_SCAN or drop STRICT_COVERAGE."
            )
        if cov.discovery_complete is False:
            raise StrictCoverageError(
                "Resource discovery was incomplete (a search hit the provider's "
                "result limit). Narrow the scan with IGNORE_REGIONS or drop "
                "STRICT_COVERAGE."
            )

    def summary(self) -> dict[str, Any] | None:
        cov = self.coverage
        if cov is None:
            return None
        return {
            "discovered": cov.discovered,
            "analysed": cov.analysed,
            "dropped": cov.dropped,
            "truncated": cov.truncated,
            "selection": cov.selection,
            "discovery_complete": cov.discovery_complete,
        }
