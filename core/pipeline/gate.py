"""Settle only what the metrics show is clearly in use, so the model never sees it."""

from __future__ import annotations

from core.pipeline.evidence import Evidence

_GIB = 1024**3

# Per type: every group must reach its minimum (a group sums its metrics) over the
# whole metrics window. Types without a table are never settled.
THRESHOLDS: dict[str, list[tuple[tuple[str, ...], float]]] = {
    "AWS::EC2::Instance": [
        (("CPUUtilization",), 20.0),
        (("NetworkIn", "NetworkOut"), float(_GIB)),
    ],
    "AWS::RDS::DBInstance": [
        (("CPUUtilization",), 20.0),
        (("DatabaseConnections",), 5.0),
    ],
}


def _clearly_active(ev: Evidence) -> bool:
    table = THRESHOLDS.get(ev.resource.resource_type)
    if not table or ev.metrics_status != "ok":
        return False
    for names, minimum in table:
        total = 0.0
        for name in names:
            value = ev.metrics.get(name)
            if not isinstance(value, (int, float)):
                return False
            total += value
        if total < minimum:
            return False
    return True


def gate(evidence: list[Evidence]) -> tuple[list[Evidence], list[Evidence]]:
    """(residual, settled), each in input order. Missing data never settles."""
    residual: list[Evidence] = []
    settled: list[Evidence] = []
    for ev in evidence:
        (settled if _clearly_active(ev) else residual).append(ev)
    return residual, settled
