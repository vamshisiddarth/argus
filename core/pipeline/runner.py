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
from core.errors import StrictCoverageError
from core.models.finding import ResourceFinding
from core.pipeline.evidence import Evidence, collect_evidence
from core.pipeline.gate import gate
from core.pipeline.triage import (
    Flagged,
    TriageResult,
    plan_budget,
    rank_for_triage,
    ranking_basis,
    run_triage,
)
from core.reports.generator import review_summary, waste_breakdown
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
    if loop.scan_window is None:
        loop.scan_window = {}
    window_info: dict[str, Any] = loop.scan_window
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
        states=loop._baseline.states,
    )
    gate_mode = scan.gate
    settled: list[Evidence] = []
    residual = evidence
    if gate_mode != "off":
        residual, settled = gate(evidence)
    settled_ids = {e.resource.resource_id for e in settled}
    ranked = rank_for_triage(residual if gate_mode == "on" else evidence)

    prompt = build_triage_prompt(
        cloud,
        ignore_regions,
        accounts,
        lookback_days=window,
        activity_days=scan.activity_lookback_days,
        rule_finding_ids=sorted(decided),
    )
    plan = plan_budget(
        ranked,
        prompt,
        settings.ai.provider,
        scan.llm_budget_usd,
        scan.triage_batch_items,
    )
    estimate = plan.full_estimate_usd
    order = ranking_basis(ranked)
    plan_line = plan.line(scan.llm_budget_usd, len(decided), order.replace("_", " "))
    window_info["llm_estimate_usd"] = estimate
    window_info["llm_plan"] = {**plan.to_dict(), "order": order, "line": plan_line}
    logger.info("llm_plan", line=plan_line)
    if scan.strict_coverage and plan.covered < plan.candidates:
        raise StrictCoverageError(
            f"{plan_line} Strict coverage is on, so the scan stopped before any "
            "model call. Raise LLM_BUDGET_USD or drop STRICT_COVERAGE."
        )
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
    window_info["llm_calibration"] = _calibration_summary(triage)

    no_data_ids = {e.resource.resource_id for e in evidence if e.metrics_status != "ok"}
    model_findings = [
        _to_finding(flag, window, no_data_ids, _resolve_confidence)
        for flag in triage.flagged
    ]
    findings = loop._merge_baseline(model_findings)
    findings = _attach_accounts(findings, accounts)

    analysed_ids = (
        {e.resource.resource_id for e in triage.analysed}
        | loop._baseline.evaluated_ids
        | (settled_ids if gate_mode == "on" else set())
    )
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
    loop.coverage.metrics_lost_to_throttling = sum(
        1 for e in evidence if _throttled(e.metrics_note)
    )
    loop.coverage.stop_reason = _stop_reason(triage, skipped)
    gate_stage: dict[str, Any] = {
        "mode": gate_mode,
        "settled": len(settled),
    }
    if gate_mode == "shadow":
        wrongly = sum(
            1 for f in triage.flagged if f.evidence.resource.resource_id in settled_ids
        )
        gate_stage["settled_but_flagged"] = wrongly
        if wrongly:
            logger.warning("gate_shadow_miss", settled_but_flagged=wrongly)
    loop.coverage.stages = {
        "rules": {
            "evaluated": len(loop._baseline.evaluated_ids),
            "findings": len(decided),
            "undecided": loop._baseline.candidates - len(loop._baseline.evaluated_ids),
        },
        "gate": gate_stage,
        "model": {
            "candidates": len(ranked) + len(cap_skipped),
            "analysed": len(triage.analysed),
            "skipped": len(triage.skipped) + len(cap_skipped),
            "stop_reason": loop.coverage.stop_reason,
            "order": order,
        },
    }

    summary = _summarise(
        findings, loop.coverage, triage, loop.tracker, len(ranked) + len(cap_skipped)
    )
    logger.info(
        "pipeline_complete",
        findings=len(findings),
        analysed=loop.coverage.analysed,
        skipped=skipped,
        spent_usd=loop.tracker.estimated_cost_usd,
        calls=triage.calls,
    )
    return findings, summary


_THROTTLE_CODES = (
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "TooManyRequestsException",
)


def _throttled(note: str | None) -> bool:
    return note is not None and note.split(":", 1)[0].strip() in _THROTTLE_CODES


def _calibration_summary(triage: TriageResult) -> dict[str, Any]:
    calls = triage.calibration
    return {
        "calls": len(calls),
        "estimated_input_tokens": sum(c["est_in"] for c in calls),
        "actual_input_tokens": sum(c["actual_in"] for c in calls),
        "estimated_output_tokens": sum(c["est_out"] for c in calls),
        "actual_output_tokens": sum(c["actual_out"] for c in calls),
        "per_call": [dict(c) for c in calls],
    }


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
    candidates: int = 0,
) -> str:
    analysed = f"Analysed {coverage.analysed} of {coverage.discovered} resources."
    if coverage.free_config_skipped:
        analysed += (
            f" {coverage.free_config_skipped} free configuration objects were "
            "skipped on purpose."
        )
    if coverage.metrics_lost_to_throttling:
        analysed += (
            f" Metrics for {coverage.metrics_lost_to_throttling} resources could "
            "not be fetched because the API kept throttling; their findings rest "
            "on less evidence."
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
        label = "estimate only, not billed, unverified" if is_estimate else "billed"
        review_n, review_usd = review_summary([f.to_dict() for f in findings])
        review = (
            f" ${review_usd:,.2f} of that is in {review_n} "
            f"finding{'s' if review_n != 1 else ''} that need human review before "
            "any action (production-like name or a large unbilled estimate)."
            if review_n
            else ""
        )
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
            + review
            + f" {analysed}"
        )
    if triage.stop_reason == "budget":
        return (
            f"Scan aborted: LLM budget of ${tracker.budget_usd:.2f} reached "
            f"(${tracker.estimated_cost_usd:.2f} spent); the findings found so far are "
            f"included. Model reviewed {len(triage.analysed)} of {candidates} "
            f"candidates, highest first; totals below are a lower bound. {body} "
            "Raise LLM_BUDGET_USD to analyse the rest."
        )
    return body
