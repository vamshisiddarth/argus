"""Run the deterministic rules over a discovered inventory."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from adapters.base import CloudAdapter, Resource
from core.baseline.rules import RULES_BY_TYPE, STATE_RULES_BY_TYPE, Rule, StateRule
from core.models.finding import ResourceFinding

logger = structlog.get_logger(__name__)

_MAX_EVALUATED = 500


@dataclass
class BaselineResult:
    findings: list[ResourceFinding] = field(default_factory=list)
    # Resources whose data was complete enough for a rule to decide, either way
    evaluated_ids: set[str] = field(default_factory=set)
    # Configuration collected for rule evaluation; reused as evidence for the model
    states: dict[str, dict[str, Any]] = field(default_factory=dict)
    candidates: int = 0  # resources of a type some rule applies to

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
    result = BaselineResult()
    _metric_rules(adapter, resources, costs, window_days, concurrency, result)
    _state_rules(adapter, resources, costs, result)
    result.findings.sort(key=lambda f: f.resource_id)
    logger.info(
        "baseline_complete",
        candidates=result.candidates,
        evaluated=len(result.evaluated_ids),
        undecided=result.candidates - len(result.evaluated_ids),
        findings=len(result.findings),
        state_collected=len(result.states),
    )
    return result


def _metric_rules(
    adapter: CloudAdapter,
    resources: list[Resource],
    costs: dict[str, float],
    window_days: int,
    concurrency: int,
    result: BaselineResult,
) -> None:
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
    result.candidates += len(candidates)
    if not candidates:
        return

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

    undecided = 0
    for resource, rule, idle, metrics in outcomes:
        if idle is None:
            undecided += 1
            continue
        result.evaluated_ids.add(resource.resource_id)
        if idle:
            result.findings.append(
                _metric_finding(resource, rule, costs, window_days, metrics)
            )
    logger.info(
        "baseline_metric_rules",
        candidates=len(candidates),
        evaluated=len(candidates) - undecided,
        undecided=undecided,
    )


def _state_rules(
    adapter: CloudAdapter,
    resources: list[Resource],
    costs: dict[str, float],
    result: BaselineResult,
) -> None:
    candidates = [r for r in resources if r.resource_type in STATE_RULES_BY_TYPE]
    result.candidates += len(candidates)
    if not candidates:
        return
    try:
        states = adapter.collect_state(candidates)
    except Exception as exc:  # noqa: BLE001
        logger.warning("baseline_state_failed", error=str(exc))
        return
    result.states = dict(states)
    for resource in sorted(candidates, key=lambda r: r.resource_id):
        state = states.get(resource.resource_id)
        rule = STATE_RULES_BY_TYPE[resource.resource_type]
        if not state:
            continue
        waste = rule.is_waste(state)
        if waste is None:
            continue
        result.evaluated_ids.add(resource.resource_id)
        if waste:
            finding = _state_finding(resource, rule, costs, state)
            if finding is not None:
                result.findings.append(finding)


def _priority(cost: float) -> str:
    return "high" if cost > 20 else "medium" if cost >= 5 else "low"


def _metric_finding(
    resource: Resource,
    rule: Rule,
    costs: dict[str, float],
    window_days: int,
    metrics: dict,
) -> ResourceFinding:
    billed = costs.get(resource.resource_id, 0.0)
    cost = billed if billed > 0 else rule.list_price_usd
    return ResourceFinding(
        resource_id=resource.resource_id,
        resource_type=resource.resource_type,
        cloud=resource.cloud,  # type: ignore[arg-type]
        region=resource.region,
        estimated_monthly_cost=round(cost, 2),
        waste_reason=rule.reason(window_days),
        recommendation=rule.recommendation,
        priority=_priority(cost),  # type: ignore[arg-type]
        metrics_summary={**metrics, "window_days": window_days},
        tags=dict(resource.tags),
        scan_time=datetime.now(tz=timezone.utc),
        name=resource.name,
        cost_basis="billed" if billed > 0 else "list_price",
        confidence="high" if window_days >= 90 else "medium",
        detected_by=f"rule:{rule.rule_id}",
    )


def _state_finding(
    resource: Resource,
    rule: StateRule,
    costs: dict[str, float],
    state: dict[str, Any],
) -> ResourceFinding | None:
    billed = costs.get(resource.resource_id, 0.0)
    cost = billed if billed > 0 else rule.monthly_cost(state)
    if cost <= 0:
        return None  # nothing measurable to save
    return ResourceFinding(
        resource_id=resource.resource_id,
        resource_type=resource.resource_type,
        cloud=resource.cloud,  # type: ignore[arg-type]
        region=resource.region,
        estimated_monthly_cost=round(cost, 2),
        waste_reason=rule.reason(state),
        recommendation=rule.recommendation,
        priority=_priority(cost),  # type: ignore[arg-type]
        metrics_summary={"state": state},
        tags=dict(resource.tags),
        scan_time=datetime.now(tz=timezone.utc),
        name=resource.name,
        cost_basis="billed" if billed > 0 else "list_price",
        confidence=rule.confidence,
        detected_by=f"rule:{rule.rule_id}",
    )
