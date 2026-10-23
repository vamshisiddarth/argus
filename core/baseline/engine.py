"""Run the deterministic rules over a discovered inventory."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from adapters.base import CloudAdapter, Resource
from core.baseline.rules import RULES_BY_TYPE, Rule
from core.models.finding import ResourceFinding

logger = structlog.get_logger(__name__)

_MAX_EVALUATED = 500


@dataclass
class BaselineResult:
    findings: list[ResourceFinding] = field(default_factory=list)
    # Resources whose metrics were complete enough for a rule to decide, either way
    evaluated_ids: set[str] = field(default_factory=set)

    @property
    def finding_ids(self) -> set[str]:
        return {f.resource_id for f in self.findings}


def run_baseline(
    adapter: CloudAdapter,
    resources: list[Resource],
    costs: dict[str, float],
    window_days: int,
    concurrency: int = 10,
) -> BaselineResult:
    candidates = sorted(
        (
            (r, RULES_BY_TYPE[r.resource_type])
            for r in resources
            if r.resource_type in RULES_BY_TYPE
            and RULES_BY_TYPE[r.resource_type].applies(r)
        ),
        key=lambda pair: pair[0].resource_id,
    )
    if len(candidates) > _MAX_EVALUATED:
        logger.warning(
            "baseline_candidates_truncated",
            candidates=len(candidates),
            evaluated=_MAX_EVALUATED,
        )
        candidates = candidates[:_MAX_EVALUATED]
    if not candidates:
        return BaselineResult()

    def evaluate(
        pair: tuple[Resource, Rule],
    ) -> tuple[Resource, Rule, bool | None, dict]:
        resource, rule = pair
        try:
            summary = adapter.get_metrics(
                resource_id=resource.resource_id,
                resource_type=resource.resource_type,
                days=window_days,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "baseline_metrics_failed",
                resource_id=resource.resource_id,
                error=str(exc),
            )
            return resource, rule, None, {}
        if summary.status != "ok":
            return resource, rule, None, {}
        return resource, rule, rule.is_idle(summary.metrics), summary.metrics

    workers = max(1, min(concurrency, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(evaluate, candidates))

    result = BaselineResult()
    for resource, rule, idle, metrics in outcomes:
        if idle is None:
            continue
        result.evaluated_ids.add(resource.resource_id)
        if idle:
            result.findings.append(
                _finding(resource, rule, costs, window_days, metrics)
            )
    logger.info(
        "baseline_complete",
        evaluated=len(result.evaluated_ids),
        findings=len(result.findings),
    )
    return result


def _finding(
    resource: Resource,
    rule: Rule,
    costs: dict[str, float],
    window_days: int,
    metrics: dict,
) -> ResourceFinding:
    billed = costs.get(resource.resource_id, 0.0)
    cost = billed if billed > 0 else rule.list_price_usd
    priority = "high" if cost > 20 else "medium" if cost >= 5 else "low"
    return ResourceFinding(
        resource_id=resource.resource_id,
        resource_type=resource.resource_type,
        cloud=resource.cloud,  # type: ignore[arg-type]
        region=resource.region,
        estimated_monthly_cost=round(cost, 2),
        waste_reason=rule.reason(window_days),
        recommendation=rule.recommendation,
        priority=priority,  # type: ignore[arg-type]
        metrics_summary={**metrics, "window_days": window_days},
        tags=dict(resource.tags),
        scan_time=datetime.now(tz=timezone.utc),
        name=resource.name,
        cost_basis="billed" if billed > 0 else "estimated",
        confidence="high" if window_days >= 90 else "medium",
        detected_by=f"rule:{rule.rule_id}",
    )
