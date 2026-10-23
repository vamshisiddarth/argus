"""
Per-resource evidence, gathered in code before the model sees anything.

Everything here is a plain read-only call through the cloud adapter. The model
never has to ask for data, so its context never grows and its spend is bounded
by what we choose to show it.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog

from adapters.base import CloudAdapter, Resource

logger = structlog.get_logger(__name__)

_MAX_TAGS = 6
_MAX_TAG_VALUE = 40
_ACTIVITY_WORKERS = 2  # CloudTrail LookupEvents allows about 2 requests/second


@dataclass
class Evidence:
    resource: Resource
    billed_cost_usd: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    metrics_status: str = "no_data"
    metrics_note: str | None = None
    last_activity: datetime | None = None
    activity_checked: bool = False

    def to_prompt(self, index: int) -> dict[str, Any]:
        """Compact JSON line for the model. `i` is how the model refers back to it."""
        r = self.resource
        line: dict[str, Any] = {
            "i": index,
            "id": _short_id(r.resource_id),
            "t": r.native_type or r.resource_type,
            "r": r.region,
        }
        if r.name:
            line["name"] = r.name[:60]
        if r.tags:
            line["tags"] = {
                k: str(v)[:_MAX_TAG_VALUE] for k, v in list(r.tags.items())[:_MAX_TAGS]
            }
        if self.billed_cost_usd:
            line["cost"] = round(self.billed_cost_usd, 2)
        usable = {k: _round(v) for k, v in self.metrics.items() if v is not None}
        if usable:
            line["m"] = usable
        if self.metrics_status != "ok":
            line["ms"] = self.metrics_status
        if self.activity_checked:
            line["la"] = (
                self.last_activity.date().isoformat()
                if self.last_activity
                else "none_in_window"
            )
        return line


def collect_evidence(
    adapter: CloudAdapter,
    resources: list[Resource],
    costs: dict[str, float],
    window_days: int,
    *,
    activity_days: int = 90,
    activity_mode: str = "auto",
    activity_cap: int = 150,
    concurrency: int = 10,
) -> list[Evidence]:
    """Evidence for every resource, in input order.

    activity_mode: "auto" looks up last activity only for resources whose metrics
    could not decide (no data or an error); "all" for every resource; "off" never.
    """
    if not resources:
        return []

    def fetch(resource: Resource) -> Evidence:
        ev = Evidence(
            resource=resource,
            billed_cost_usd=costs.get(resource.resource_id) or None,
        )
        try:
            summary = adapter.get_metrics(
                resource_id=resource.resource_id,
                resource_type=resource.resource_type,
                days=window_days,
            )
        except Exception as exc:  # noqa: BLE001
            ev.metrics_status = "error"
            ev.metrics_note = str(exc)[:200]
            return ev
        ev.metrics = dict(summary.metrics)
        ev.metrics_status = summary.status or ("ok" if summary.has_data else "no_data")
        ev.metrics_note = summary.error
        return ev

    workers = max(1, min(concurrency, len(resources)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        evidence = list(pool.map(fetch, resources))

    if activity_mode != "off":
        wanted = [
            e for e in evidence if activity_mode == "all" or e.metrics_status != "ok"
        ][:activity_cap]
        _look_up_activity(adapter, wanted)
    logger.info(
        "evidence_collected",
        resources=len(evidence),
        metrics_ok=sum(1 for e in evidence if e.metrics_status == "ok"),
        activity_checked=sum(1 for e in evidence if e.activity_checked),
    )
    return evidence


def _look_up_activity(adapter: CloudAdapter, items: list[Evidence]) -> None:
    def look(ev: Evidence) -> None:
        try:
            ev.last_activity = adapter.get_last_activity(
                resource_id=ev.resource.resource_id,
                resource_type=ev.resource.resource_type,
            )
            ev.activity_checked = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "activity_lookup_failed",
                resource_id=ev.resource.resource_id,
                error=str(exc),
            )

    if not items:
        return
    with ThreadPoolExecutor(max_workers=_ACTIVITY_WORKERS) as pool:
        list(pool.map(look, items))


_SEGMENT = re.compile(r"[^:/]+$")


def _short_id(resource_id: str) -> str:
    match = _SEGMENT.search(resource_id)
    return match.group(0) if match else resource_id


def _round(value: Any) -> Any:
    return round(value, 4) if isinstance(value, float) else value
