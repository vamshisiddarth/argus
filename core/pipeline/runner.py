"""The default scan engine: discover, decide by rule, gather evidence, triage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from adapters.base import Resource
from core.agent.prompts import build_triage_prompt
from core.agent.selection import select_candidates
from core.baseline import BaselineResult, run_baseline
from core.config import get_settings
from core.models.finding import ResourceFinding
from core.pipeline.evidence import Evidence, collect_evidence
from core.pipeline.triage import (
    Flagged,
    TriageResult,
    estimate_cost,
    rank_for_triage,
    run_triage,
)
from core.reports.generator import waste_breakdown
from core.token_tracker import TokenTracker

if TYPE_CHECKING:
    from core.agent.loop import AgentLoop

logger = structlog.get_logger(__name__)


def run_pipeline(
    loop: AgentLoop,
    cloud: str,
    ignore_regions: list[str],
    accounts: list[dict[str, Any]],
) -> tuple[list[ResourceFinding], str]:
    from core.agent.loop import (
        _attach_accounts,
        _build_coverage,
        _free_config_count,
        _lookback_days,
        _resolve_confidence,
    )

    settings = get_settings()
    scan = settings.scan
    loop.tracker = TokenTracker(
        budget_usd=scan.llm_budget_usd, provider=settings.ai.provider
    )
    window = _lookback_days()

    resources, costs = loop._discover_and_cost(ignore_regions)
    window_info = loop.scan_window
    window_info["llm_budget_usd"] = scan.llm_budget_usd
    if not resources:
        window_info["llm_estimate_usd"] = 0.0
        window_info["llm_spent_usd"] = 0.0
        return [], "No resources were found to analyse."

    loop._baseline = BaselineResult()
    if scan.baseline_rules:
        loop._baseline = run_baseline(
            loop._adapter, resources, costs, window, scan.adapter_concurrency
        )
    decided = loop._baseline.finding_ids
    pool = [r for r in resources if r.resource_id not in decided]

    cap_skipped: list[Resource] = []
    window_info["max_resources"] = (
        scan.max_resources if scan.max_resources_override else None
    )
    window_info["max_resources_source"] = scan.max_resources_source
    if scan.max_resources_override is not None:
        chosen, _ = select_candidates(pool, costs, scan.max_resources_override)
        chosen_ids = {r.resource_id for r in chosen}
        cap_skipped = [r for r in pool if r.resource_id not in chosen_ids]
        pool = chosen
        window_info["max_resources_source"] = "explicit"
    else:
        window_info["max_resources_source"] = "budget"

    evidence = collect_evidence(
        loop._adapter,
        pool,
        costs,
        window,
        activity_days=scan.activity_lookback_days,
        activity_mode=scan.activity_lookup,
        concurrency=scan.adapter_concurrency,
    )
    ranked = rank_for_triage(evidence)

    prompt = build_triage_prompt(
        cloud,
        ignore_regions,
        accounts,
        lookback_days=window,
        activity_days=scan.activity_lookback_days,
        rule_finding_ids=sorted(decided),
    )
    estimate = estimate_cost(ranked, prompt, settings.ai.provider)
    window_info["llm_estimate_usd"] = estimate
    logger.info(
        "llm_estimate",
        resources=len(ranked),
        estimated_usd=estimate,
        budget_usd=scan.llm_budget_usd,
        fits_budget=not scan.llm_budget_usd or estimate <= scan.llm_budget_usd,
    )

    triage = run_triage(
        loop._ai,
        loop.tracker,
        ranked,
        prompt,
        max_batch_items=scan.triage_batch_items,
    )
    window_info["llm_spent_usd"] = loop.tracker.estimated_cost_usd

    no_data_ids = {e.resource.resource_id for e in evidence if e.metrics_status != "ok"}
    model_findings = [
        _to_finding(flag, window, no_data_ids, _resolve_confidence)
        for flag in triage.flagged
    ]
    findings = loop._merge_baseline(model_findings)
    findings = _attach_accounts(findings, accounts)

    analysed_ids = {
        e.resource.resource_id for e in triage.analysed
    } | loop._baseline.evaluated_ids
    analysed = [r for r in resources if r.resource_id in analysed_ids]
    loop.coverage = _build_coverage(
        resources,
        analysed,
        costs,
        "risk_ranked",
        len(resources),
        getattr(loop._adapter, "discovery_complete", None),
        _free_config_count(loop._adapter),
    )
    skipped: dict[str, int] = {}
    for _, reason in triage.skipped:
        skipped[reason] = skipped.get(reason, 0) + 1
    if cap_skipped:
        skipped["cap"] = len(cap_skipped)
    loop.coverage.skipped_by_reason = skipped
    loop.coverage.stop_reason = _stop_reason(triage, skipped)

    summary = _summarise(findings, loop.coverage, triage, loop.tracker)
    logger.info(
        "pipeline_complete",
        findings=len(findings),
        analysed=loop.coverage.analysed,
        skipped=skipped,
        spent_usd=loop.tracker.estimated_cost_usd,
        calls=triage.calls,
    )
    return findings, summary


def _stop_reason(triage: TriageResult, skipped: dict[str, int]) -> str | None:
    if triage.stop_reason:
        return triage.stop_reason
    if skipped.get("llm_failure"):
        return "llm_failure"
    if skipped.get("cap"):
        return "cap"
    return None


def _to_finding(
    flag: Flagged, window: int, no_data_ids: set[str], resolve: Any
) -> ResourceFinding:
    ev: Evidence = flag.evidence
    r = ev.resource
    billed = ev.billed_cost_usd or 0.0
    if billed > 0:
        cost, basis = billed, "billed"
    elif flag.model_cost_usd > 0:
        cost, basis = flag.model_cost_usd, "model_estimate"
    else:
        cost, basis = 0.0, "unknown"
    return ResourceFinding(
        resource_id=r.resource_id,
        resource_type=r.resource_type,
        cloud=r.cloud,  # type: ignore[arg-type]
        region=r.region,
        estimated_monthly_cost=round(cost, 2),
        waste_reason=flag.waste_reason,
        recommendation=flag.recommendation,
        priority=flag.priority,  # type: ignore[arg-type]
        metrics_summary={
            "metrics": {k: v for k, v in ev.metrics.items() if v is not None},
            "metrics_status": ev.metrics_status,
            "has_data": ev.metrics_status == "ok",
            "window_days": window,
            "last_activity_checked": ev.activity_checked,
        },
        tags=dict(r.tags),
        scan_time=datetime.now(tz=timezone.utc),
        name=r.name,
        last_activity=ev.last_activity,
        cost_basis=basis,
        confidence=resolve(flag.confidence, r.resource_id, no_data_ids, window),
        detected_by="model",
    )


def _summarise(
    findings: list[ResourceFinding],
    coverage: Any,
    triage: TriageResult,
    tracker: TokenTracker,
) -> str:
    analysed = f"Analysed {coverage.analysed} of {coverage.discovered} resources."
    if coverage.free_config_skipped:
        analysed += (
            f" {coverage.free_config_skipped} free configuration objects were "
            "skipped on purpose."
        )
    if not findings:
        body = f"No wasteful resources were identified. {analysed}"
    else:
        total = sum(f.estimated_monthly_cost for f in findings)
        by_priority = {
            p: sum(1 for f in findings if f.priority == p)
            for p in ("high", "medium", "low")
        }
        parts = ", ".join(f"{n} {p}" for p, n in by_priority.items() if n)
        _, is_estimate = waste_breakdown([f.to_dict() for f in findings])
        label = "not billed" if is_estimate else "billed"
        top = ", ".join(
            f"{f.resource_id.split('/')[-1]} (${f.estimated_monthly_cost:,.2f})"
            for f in sorted(
                findings, key=lambda x: (-x.estimated_monthly_cost, x.resource_id)
            )[:3]
            if f.estimated_monthly_cost
        )
        body = (
            f"Found {len(findings)} resources worth reviewing, about "
            f"${total:,.2f}/month ({label}): {parts} priority."
            + (f" Largest: {top}." if top else "")
            + f" {analysed}"
        )
    if triage.stop_reason == "budget":
        return (
            f"Scan aborted: LLM budget of ${tracker.budget_usd:.2f} reached "
            f"(${tracker.estimated_cost_usd:.2f} spent); the findings found so far are "
            f"included. {body} Raise LLM_BUDGET_USD to analyse the rest."
        )
    return body
