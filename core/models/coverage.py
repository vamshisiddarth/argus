"""What a scan actually looked at: discovered vs analysed, per type and overall."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TypeCoverage:
    discovered: int
    analysed: int


@dataclass
class Coverage:
    discovered: int
    analysed: int
    selection: str  # "cost_desc" | "stratified_by_type" | "mixed"
    cost_data_available: bool
    regions_covered: list[str] = field(default_factory=list)
    types: dict[str, TypeCoverage] = field(default_factory=dict)
    # False when the discovery API could not return everything (e.g. AWS Resource
    # Explorer's 1,000-result limit); None when the adapter does not say.
    discovery_complete: bool | None = None
    # Why resources were not analysed: "budget", "cap" or "llm_failure"
    stop_reason: str | None = None
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    # Free configuration objects (subnets, IAM roles, ...) skipped on purpose;
    # they are not part of `discovered`.
    free_config_skipped: int = 0
    # Resources whose metrics could not be fetched because the API kept throttling.
    metrics_lost_to_throttling: int = 0

    @property
    def dropped(self) -> int:
        return self.discovered - self.analysed

    @property
    def truncated(self) -> bool:
        return self.dropped > 0

    @classmethod
    def empty(cls) -> Coverage:
        return cls(0, 0, "stratified_by_type", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovered": self.discovered,
            "analysed": self.analysed,
            "dropped": self.dropped,
            "truncated": self.truncated,
            "selection": self.selection,
            "cost_data_available": self.cost_data_available,
            "discovery_complete": self.discovery_complete,
            "stop_reason": self.stop_reason,
            "skipped_by_reason": dict(sorted(self.skipped_by_reason.items())),
            "free_config_skipped": self.free_config_skipped,
            "metrics_lost_to_throttling": self.metrics_lost_to_throttling,
            "regions_covered": sorted(self.regions_covered),
            "types": {
                t: {"discovered": c.discovered, "analysed": c.analysed}
                for t, c in sorted(self.types.items())
            },
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Coverage:
        return cls(
            discovered=d["discovered"],
            analysed=d["analysed"],
            selection=d.get("selection", "cost_desc"),
            cost_data_available=d.get("cost_data_available", False),
            discovery_complete=d.get("discovery_complete"),
            stop_reason=d.get("stop_reason"),
            skipped_by_reason=dict(d.get("skipped_by_reason", {})),
            free_config_skipped=int(d.get("free_config_skipped", 0)),
            metrics_lost_to_throttling=int(d.get("metrics_lost_to_throttling", 0)),
            regions_covered=list(d.get("regions_covered", [])),
            types={
                t: TypeCoverage(c["discovered"], c["analysed"])
                for t, c in d.get("types", {}).items()
            },
        )

    @staticmethod
    def merge(items: list[Coverage]) -> Coverage:
        """Combine per-account coverage into one overall figure."""
        if not items:
            return Coverage.empty()
        types: dict[str, TypeCoverage] = {}
        for item in items:
            for name, tc in item.types.items():
                prev = types.get(name, TypeCoverage(0, 0))
                types[name] = TypeCoverage(
                    prev.discovered + tc.discovered, prev.analysed + tc.analysed
                )
        flags = [i.discovery_complete for i in items]
        if False in flags:
            discovery: bool | None = False
        elif all(f is True for f in flags):
            discovery = True
        else:
            discovery = None
        skipped: dict[str, int] = {}
        for item in items:
            for reason, n in item.skipped_by_reason.items():
                skipped[reason] = skipped.get(reason, 0) + n
        stops = [i.stop_reason for i in items if i.stop_reason]
        rules = {i.selection for i in items}
        return Coverage(
            discovered=sum(i.discovered for i in items),
            analysed=sum(i.analysed for i in items),
            selection=rules.pop() if len(rules) == 1 else "mixed",
            cost_data_available=all(i.cost_data_available for i in items),
            regions_covered=sorted({r for i in items for r in i.regions_covered}),
            types=types,
            discovery_complete=discovery,
            stop_reason=stops[0] if stops else None,
            skipped_by_reason=skipped,
            free_config_skipped=sum(i.free_config_skipped for i in items),
            metrics_lost_to_throttling=sum(i.metrics_lost_to_throttling for i in items),
        )
