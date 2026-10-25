"""
Batch triage: show the model evidence, get findings back.

Every batch is a separate, stateless call (one user message, same system prompt),
so cost grows linearly with the number of resources instead of quadratically with
a conversation. Findings from a finished batch are never discarded, and the loop
stops before a batch that would overspend rather than after.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

import structlog

from ai.base import AIProvider, AIResponse, Message, Tool
from core.agent.prompts import REPORT_FINDINGS_TOOL
from core.agent.selection import HIGH_IMPACT_TYPES
from core.errors import AgentDidNotSubmitError
from core.pipeline.evidence import Evidence
from core.pricing.aws import list_price_proxy
from core.token_tracker import (
    _DEFAULT_PRICING,
    _PRICING,
    BudgetExceededError,
    TokenTracker,
)

logger = structlog.get_logger(__name__)

_CHARS_PER_TOKEN = 3.5
_PRIORITIES = ("high", "medium", "low")
_CONFIDENCES = ("low", "medium", "high")
_FLAGGED_FRACTION = 0.25  # assumed share of a batch the model flags (for estimates)
_TOKENS_PER_FINDING = 110
_REPLY_OVERHEAD_TOKENS = 100
_MIN_CORRECTION = 0.5
_MAX_CORRECTION = 3.0

_TOOL = Tool(
    name=REPORT_FINDINGS_TOOL["name"],
    description=REPORT_FINDINGS_TOOL["description"],
    input_schema=REPORT_FINDINGS_TOOL["input_schema"],
)


@dataclass
class Flagged:
    index: int
    evidence: Evidence
    waste_reason: str
    recommendation: str
    priority: str
    confidence: str
    model_cost_usd: float


@dataclass
class TriageResult:
    flagged: list[Flagged] = field(default_factory=list)
    analysed: list[Evidence] = field(default_factory=list)
    skipped: list[tuple[Evidence, str]] = field(default_factory=list)
    stop_reason: str | None = None  # "budget" | None
    failed_batches: int = 0
    calls: int = 0
    # One entry per model call: estimated against actual tokens, counts only.
    calibration: list[dict[str, int]] = field(default_factory=list)


def _dollars(e: Evidence) -> float:
    """Billed cost if there is one, else a list-price stand-in. For ordering only."""
    if e.billed_cost_usd:
        return e.billed_cost_usd
    return list_price_proxy(e.resource.resource_type, e.state)


def _idle_rank(e: Evidence) -> int:
    """0 looks idle, 1 unknown, 2 shows activity. Ordering only."""
    if e.metrics_status != "ok":
        return 1
    numbers = [abs(v) for v in e.metrics.values() if isinstance(v, (int, float))]
    return 0 if numbers and sum(numbers) == 0 else 2


def rank_for_triage(evidence: list[Evidence]) -> list[Evidence]:
    """Most worth the model's attention first; fully deterministic."""

    def key(e: Evidence) -> tuple:
        return (
            -_dollars(e),
            _idle_rank(e),
            0 if e.resource.resource_type in HIGH_IMPACT_TYPES else 1,
            e.resource.resource_type,
            e.resource.resource_id,
        )

    return sorted(evidence, key=key)


def ranking_basis(evidence: list[Evidence]) -> str:
    """What the order was built on: billed_cost, list_price or type_risk."""
    if any(e.billed_cost_usd for e in evidence):
        return "billed_cost"
    if any(_dollars(e) for e in evidence):
        return "list_price"
    return "type_risk"


def _tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN) + 1


def _line_tokens(ev: Evidence, index: int) -> int:
    return _tokens(json.dumps(ev.to_prompt(index), separators=(",", ":")))


def estimate_cost(
    evidence: list[Evidence],
    system_prompt: str,
    provider: str,
    max_batch_items: int = 60,
) -> float:
    """Expected LLM spend for these resources, before any call is made."""
    return plan_budget(
        evidence, system_prompt, provider, 0.0, max_batch_items
    ).full_estimate_usd


@dataclass(frozen=True)
class Plan:
    candidates: int
    covered: int
    full_estimate_usd: float
    covered_estimate_usd: float

    def line(
        self,
        budget_usd: float,
        rules_decided: int,
        order: str,
        gate_settled: int = 0,
    ) -> str:
        after = f"rules ({rules_decided})"
        if gate_settled:
            after += f" and gate ({gate_settled})"
        head = f"LLM plan: {self.candidates} residual candidates after {after}."
        if self.covered >= self.candidates:
            return (
                f"{head} Budget covers all {self.candidates} residual candidates "
                f"(estimated ${self.full_estimate_usd:,.2f})."
            )
        needed = math.ceil(self.full_estimate_usd * 100) / 100
        return (
            f"{head} Full pass ~${self.full_estimate_usd:,.2f} (estimate). "
            f"Budget ${budget_usd:,.2f} covers ~{self.covered} of {self.candidates} "
            f"(highest first by {order}). "
            f"Set LLM_BUDGET_USD={needed:.2f} for full coverage."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "covered": self.covered,
            "full_estimate_usd": self.full_estimate_usd,
            "covered_estimate_usd": self.covered_estimate_usd,
        }


def plan_budget(
    evidence: list[Evidence],
    system_prompt: str,
    provider: str,
    budget_usd: float,
    max_batch_items: int = 60,
    max_batch_tokens: int = 6000,
) -> Plan:
    """What a budget buys: whole batches, in the order given, before any call."""
    if not evidence:
        return Plan(0, 0, 0.0, 0.0)
    in_rate, out_rate = _PRICING.get(provider, _DEFAULT_PRICING)
    system_tokens = _tokens(system_prompt)
    full = covered_cost = 0.0
    covered = 0
    fits = True
    for batch in _make_batches(
        list(enumerate(evidence)), max_batch_items, max_batch_tokens
    ):
        cost = _batch_estimate(batch, system_tokens, in_rate, out_rate)
        full += cost
        if fits and (budget_usd <= 0 or covered_cost + cost <= budget_usd):
            covered_cost += cost
            covered += len(batch)
        else:
            fits = False
    return Plan(len(evidence), covered, round(full, 4), round(covered_cost, 4))


def _batch_tokens(
    batch: list[tuple[int, Evidence]], system_tokens: int
) -> tuple[int, int]:
    body = sum(_line_tokens(ev, i) for i, ev in batch)
    out_tokens = _REPLY_OVERHEAD_TOKENS + int(
        len(batch) * _FLAGGED_FRACTION * _TOKENS_PER_FINDING
    )
    return system_tokens + body, out_tokens


def _batch_estimate(
    batch: list[tuple[int, Evidence]],
    system_tokens: int,
    in_rate: float,
    out_rate: float,
) -> float:
    in_tokens, out_tokens = _batch_tokens(batch, system_tokens)
    return (in_tokens * in_rate + out_tokens * out_rate) / 1_000_000


def _correction(result: TriageResult, in_rate: float, out_rate: float) -> float:
    """How much more (or less) calls really cost than we estimated, clamped."""
    est = sum(
        c["est_in"] * in_rate + c["est_out"] * out_rate for c in result.calibration
    )
    actual = sum(
        c["actual_in"] * in_rate + c["actual_out"] * out_rate
        for c in result.calibration
    )
    if est <= 0:
        return 1.0
    return min(_MAX_CORRECTION, max(_MIN_CORRECTION, actual / est))


def _make_batches(
    items: list[tuple[int, Evidence]], max_items: int, max_tokens: int
) -> list[list[tuple[int, Evidence]]]:
    batches: list[list[tuple[int, Evidence]]] = []
    current: list[tuple[int, Evidence]] = []
    used = 0
    for index, ev in items:
        cost = _line_tokens(ev, index)
        if current and (len(current) >= max_items or used + cost > max_tokens):
            batches.append(current)
            current, used = [], 0
        current.append((index, ev))
        used += cost
    if current:
        batches.append(current)
    return batches


def run_triage(
    ai: AIProvider,
    tracker: TokenTracker,
    evidence: list[Evidence],
    system_prompt: str,
    *,
    max_batch_items: int = 60,
    max_batch_tokens: int = 6000,
) -> TriageResult:
    """Triage `evidence` in the order given (rank it first)."""
    result = TriageResult()
    if not evidence:
        return result

    in_rate, out_rate = _PRICING.get(tracker.provider, _DEFAULT_PRICING)
    system_tokens = _tokens(system_prompt)
    queue = _make_batches(list(enumerate(evidence)), max_batch_items, max_batch_tokens)

    while queue:
        batch = queue.pop(0)
        if result.stop_reason:
            result.skipped += [(ev, "budget") for _, ev in batch]
            continue
        correction = _correction(result, in_rate, out_rate)
        if _would_overspend(
            tracker, batch, system_tokens, in_rate, out_rate, correction
        ):
            logger.warning("triage_budget_stop", remaining_batches=len(queue) + 1)
            result.stop_reason = "budget"
            result.skipped += [(ev, "budget") for _, ev in batch]
            continue

        response = _call(ai, tracker, batch, system_prompt, result)
        if response is None:
            continue  # budget crossed on this call; its findings were still read
        findings = _extract(response)
        if findings is None:
            halves = _split(batch) if response.stop_reason == "max_tokens" else None
            if halves:
                queue[:0] = halves
                continue
            retry = _retry_once(ai, tracker, batch, system_prompt, result, response)
            findings = _extract(retry) if retry is not None else None
            if findings is None:
                if result.stop_reason == "budget":
                    result.skipped += [(ev, "budget") for _, ev in batch]
                    continue
                result.failed_batches += 1
                result.skipped += [(ev, "llm_failure") for _, ev in batch]
                continue
        _accept(result, batch, findings)

    if result.failed_batches and not result.analysed:
        raise AgentDidNotSubmitError(
            "The model never returned findings for any batch (no report_findings "
            "call). Check the provider and AI_MAX_TOKENS."
        )
    return result


def _would_overspend(
    tracker: TokenTracker,
    batch: list[tuple[int, Evidence]],
    system_tokens: int,
    in_rate: float,
    out_rate: float,
    correction: float = 1.0,
) -> bool:
    if tracker.budget_usd <= 0:
        return False
    estimate = _batch_estimate(batch, system_tokens, in_rate, out_rate) * correction
    return tracker.estimated_cost_usd + estimate > tracker.budget_usd


def _message(batch: list[tuple[int, Evidence]]) -> Message:
    lines = "\n".join(
        json.dumps(ev.to_prompt(i), separators=(",", ":"), default=str)
        for i, ev in batch
    )
    return Message(
        role="user",
        text=f"Resources to review ({len(batch)}):\n{lines}\n\nCall report_findings.",
    )


def _call(
    ai: AIProvider,
    tracker: TokenTracker,
    batch: list[tuple[int, Evidence]],
    system_prompt: str,
    result: TriageResult,
    extra: list[Message] | None = None,
) -> AIResponse | None:
    messages = [_message(batch), *(extra or [])]
    response = ai.chat(messages, [_TOOL], system_prompt=system_prompt)
    result.calls += 1
    est_in, est_out = _batch_tokens(batch, _tokens(system_prompt))
    result.calibration.append(
        {
            "items": len(batch),
            "est_in": est_in,
            "est_out": est_out,
            "actual_in": response.input_tokens,
            "actual_out": response.output_tokens,
        }
    )
    try:
        tracker.record(response.input_tokens, response.output_tokens)
    except BudgetExceededError:
        # Already paid for: read this response, but make no further calls.
        result.stop_reason = "budget"
    return response


def _retry_once(
    ai: AIProvider,
    tracker: TokenTracker,
    batch: list[tuple[int, Evidence]],
    system_prompt: str,
    result: TriageResult,
    previous: AIResponse,
) -> AIResponse | None:
    if result.stop_reason == "budget":
        return None
    reminder = [
        Message(role="assistant", text=previous.text or "..."),
        Message(
            role="user",
            text="You did not call report_findings. Call it now (empty list if none).",
        ),
    ]
    return _call(ai, tracker, batch, system_prompt, result, reminder)


def _split(
    batch: list[tuple[int, Evidence]],
) -> list[list[tuple[int, Evidence]]] | None:
    if len(batch) < 2:
        return None
    mid = len(batch) // 2
    return [batch[:mid], batch[mid:]]


def _extract(response: AIResponse) -> list[dict[str, Any]] | None:
    for call in response.tool_calls:
        if call.name == "report_findings":
            findings = call.arguments.get("findings")
            return findings if isinstance(findings, list) else []
    return None


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _accept(
    result: TriageResult,
    batch: list[tuple[int, Evidence]],
    findings: list[dict[str, Any]],
) -> None:
    by_index = dict(batch)
    seen: set[int] = set()
    for raw in findings:
        if not isinstance(raw, dict):
            continue
        raw_index = raw.get("i")
        if raw_index is None:
            continue
        try:
            idx = int(raw_index)
        except (TypeError, ValueError):
            continue
        if idx not in by_index or idx in seen:
            continue
        seen.add(idx)
        cost = raw.get("estimated_monthly_cost")
        result.flagged.append(
            Flagged(
                index=idx,
                evidence=by_index[idx],
                waste_reason=str(raw.get("waste_reason", ""))[:400],
                recommendation=str(raw.get("recommendation", ""))[:400],
                priority=_choice(raw.get("priority"), _PRIORITIES, "low"),
                confidence=_choice(raw.get("confidence"), _CONFIDENCES, "medium"),
                model_cost_usd=(
                    float(cost) if isinstance(cost, (int, float)) and cost > 0 else 0.0
                ),
            )
        )
    result.analysed += [ev for _, ev in batch]
