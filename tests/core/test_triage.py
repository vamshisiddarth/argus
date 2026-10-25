from unittest.mock import MagicMock

import pytest

from adapters.base import Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.errors import AgentDidNotSubmitError
from core.pipeline.evidence import Evidence
from core.pipeline.triage import (
    estimate_cost,
    plan_budget,
    rank_for_triage,
    ranking_basis,
    run_triage,
)
from core.token_tracker import TokenTracker

VOL = "AWS::EC2::Volume"
NAT = "AWS::EC2::NatGateway"


def _ev(n, rtype=VOL, cost=None, status="ok"):
    r = Resource(
        f"arn:aws:ec2:us-east-1:1:volume/vol-{n:03d}", rtype, "aws", "us-east-1"
    )
    return Evidence(
        r, billed_cost_usd=cost, metrics={"ops": 0.0}, metrics_status=status
    )


def _report(findings, in_tok=1000, out_tok=100):
    return AIResponse(
        "tool_use",
        None,
        [ToolCall("t", "report_findings", {"findings": findings})],
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def _finding(i, **kw):
    base = {
        "i": i,
        "waste_reason": "0 ops in 14d",
        "recommendation": "delete",
        "priority": "high",
        "confidence": "high",
        "estimated_monthly_cost": 8.0,
    }
    base.update(kw)
    return base


def _run(evidence, responses, budget=0.0, **kw):
    ai = MagicMock(spec=AIProvider)
    ai.chat.side_effect = responses
    tracker = TokenTracker(budget_usd=budget)
    result = run_triage(ai, tracker, evidence, system_prompt="SYS", **kw)
    return result, ai, tracker


def test_findings_are_mapped_back_to_their_evidence_by_index():
    evidence = [_ev(0), _ev(1), _ev(2)]

    result, _, _ = _run(evidence, [_report([_finding(1)])])

    assert [f.evidence.resource.resource_id[-7:] for f in result.flagged] == ["vol-001"]
    flagged = result.flagged[0]
    assert flagged.waste_reason == "0 ops in 14d"
    assert flagged.priority == "high" and flagged.confidence == "high"
    assert flagged.model_cost_usd == 8.0
    assert len(result.analysed) == 3


def test_empty_report_is_a_valid_clean_batch():
    result, _, _ = _run([_ev(0), _ev(1)], [_report([])])

    assert result.flagged == []
    assert len(result.analysed) == 2 and result.skipped == []


def test_invalid_indexes_and_fields_are_sanitised():
    bad = [
        _finding(99),  # not in the batch
        _finding(0, priority="URGENT", confidence="certain", estimated_monthly_cost=-5),
        {"i": "1", "waste_reason": "x", "recommendation": "y", "priority": "low"},
    ]

    result, _, _ = _run([_ev(0), _ev(1)], [_report(bad)])

    by_idx = {f.index: f for f in result.flagged}
    assert set(by_idx) == {0, 1}
    assert by_idx[0].priority == "low" and by_idx[0].confidence == "medium"
    assert by_idx[0].model_cost_usd == 0.0


def test_every_call_is_stateless_and_carries_the_system_prompt():
    evidence = [_ev(i) for i in range(6)]

    _, ai, _ = _run(
        evidence, [_report([]), _report([]), _report([])], max_batch_items=2
    )

    assert ai.chat.call_count == 3
    for call in ai.chat.call_args_list:
        assert len(call.args[0]) == 1  # one user message, no history
        assert call.kwargs["system_prompt"] == "SYS"
        assert [t.name for t in call.args[1]] == ["report_findings"]


def test_batches_respect_the_token_budget_per_batch():
    evidence = [_ev(i) for i in range(10)]

    _, ai, _ = _run(
        evidence, [_report([])] * 10, max_batch_items=100, max_batch_tokens=100
    )

    assert ai.chat.call_count > 1


def test_budget_stops_before_a_batch_that_would_overspend():
    evidence = [_ev(i) for i in range(4)]
    ai = MagicMock(spec=AIProvider)
    tracker = TokenTracker(budget_usd=0.5)
    tracker.record(166_000, 0)  # $0.498 already spent

    result = run_triage(ai, tracker, evidence, system_prompt="SYS", max_batch_items=2)

    ai.chat.assert_not_called()
    assert result.stop_reason == "budget"
    assert len(result.skipped) == 4
    assert all(reason == "budget" for _, reason in result.skipped)


def test_findings_from_finished_batches_survive_a_later_budget_stop():
    evidence = [_ev(i) for i in range(4)]
    responses = [
        _report([_finding(0)], in_tok=100_000, out_tok=1000),  # $0.315
        _report([_finding(2)], in_tok=100_000, out_tok=1000),  # crosses $0.5
    ]

    result, ai, _ = _run(evidence, responses, budget=0.5, max_batch_items=2)

    assert sorted(f.index for f in result.flagged) == [0, 2]  # nothing discarded
    assert result.stop_reason == "budget"


def test_a_call_that_crosses_the_budget_keeps_its_own_findings():
    evidence = [_ev(i) for i in range(4)]
    responses = [_report([_finding(0)], in_tok=400_000, out_tok=1000)]  # $1.2 > 0.5

    result, _, _ = _run(evidence, responses, budget=0.5, max_batch_items=2)

    assert [f.index for f in result.flagged] == [0]
    assert result.stop_reason == "budget"
    assert len(result.skipped) == 2


def test_unlimited_budget_never_stops():
    evidence = [_ev(i) for i in range(4)]

    result, _, _ = _run(
        evidence,
        [_report([], in_tok=1_000_000)] * 2,
        budget=0,
        max_batch_items=2,
    )

    assert result.stop_reason is None and result.skipped == []


def test_a_cut_off_response_splits_the_batch_and_retries():
    evidence = [_ev(i) for i in range(4)]
    responses = [
        AIResponse("max_tokens", "partial...", [], input_tokens=500, output_tokens=400),
        _report([_finding(0)]),
        _report([_finding(3)]),
    ]

    result, ai, _ = _run(evidence, responses)

    assert ai.chat.call_count == 3
    assert sorted(f.index for f in result.flagged) == [0, 3]
    assert len(result.analysed) == 4


def test_a_single_resource_that_keeps_getting_cut_off_is_marked_failed():
    cut = AIResponse("max_tokens", "x", [])

    result, _, _ = _run([_ev(0), _ev(1)], [cut, cut, _report([])], max_batch_items=1)

    assert len(result.analysed) == 1
    assert [reason for _, reason in result.skipped] == ["llm_failure"]
    assert result.failed_batches == 1


def test_no_tool_call_is_retried_once_then_the_batch_fails_others_continue():
    evidence = [_ev(i) for i in range(4)]
    no_call = AIResponse("end_turn", "all fine", [])
    responses = [no_call, no_call, _report([_finding(2)])]

    result, ai, _ = _run(evidence, responses, max_batch_items=2)

    assert ai.chat.call_count == 3
    assert [f.index for f in result.flagged] == [2]
    assert [r for _, r in result.skipped] == ["llm_failure", "llm_failure"]
    assert result.failed_batches == 1


def test_if_every_batch_fails_the_scan_fails_loudly():
    no_call = AIResponse("end_turn", "all fine", [])

    with pytest.raises(AgentDidNotSubmitError):
        _run([_ev(0), _ev(1)], [no_call] * 4)


def test_estimate_scales_with_resources_and_is_zero_for_none():
    small = estimate_cost([_ev(i) for i in range(10)], "SYS", provider="anthropic")
    large = estimate_cost([_ev(i) for i in range(100)], "SYS", provider="anthropic")

    assert 0 < small < large
    assert estimate_cost([], "SYS", provider="anthropic") == 0.0


def test_ranking_is_deterministic_and_puts_costly_and_high_impact_first():
    evidence = [
        _ev(3),
        _ev(1, cost=50.0),
        _ev(2, rtype=NAT),
        _ev(0),
        _ev(4, cost=5.0),
    ]

    ranked = rank_for_triage(evidence)

    ids = [e.resource.resource_id[-7:] for e in ranked]
    assert ids[0] == "vol-001"  # highest billed cost
    assert ranked[1].resource.resource_type == NAT  # list price $32.85 beats billed $5
    assert ids[2] == "vol-004"
    assert ids[3:] == ["vol-000", "vol-003"]
    assert [
        e.resource.resource_id for e in rank_for_triage(list(reversed(evidence)))
    ] == [e.resource.resource_id for e in ranked]


def test_every_call_records_estimated_against_actual_tokens():
    evidence = [_ev(0), _ev(1)]

    result, _, _ = _run(evidence, [_report([], in_tok=900, out_tok=50)])

    (call,) = result.calibration
    assert call["items"] == 2
    assert call["actual_in"] == 900 and call["actual_out"] == 50
    assert call["est_in"] > 0 and call["est_out"] > 0


def test_remaining_estimate_is_scaled_by_what_calls_really_cost():
    evidence = [_ev(i) for i in range(5)]
    est = estimate_cost(evidence[:1], "SYS", "anthropic")
    k = int(3 * est * 1_000_000 / 18)
    responses = [_report([], in_tok=k, out_tok=k) for _ in range(5)]

    result, ai, _ = _run(evidence, responses, budget=est * 3 * 2.5, max_batch_items=1)

    assert ai.chat.call_count == 2
    assert result.stop_reason == "budget"
    assert len(result.analysed) == 2 and len(result.skipped) == 3


def test_plan_with_no_budget_covers_every_candidate():
    evidence = [_ev(i) for i in range(10)]

    plan = plan_budget(evidence, "SYS", "anthropic", budget_usd=0.0)

    assert (plan.candidates, plan.covered) == (10, 10)
    assert plan.full_estimate_usd == estimate_cost(evidence, "SYS", "anthropic")


def test_plan_covers_whole_batches_that_fit_the_budget():
    evidence = [_ev(i) for i in range(10)]
    one_batch = estimate_cost(evidence[:2], "SYS", "anthropic")

    plan = plan_budget(
        evidence, "SYS", "anthropic", budget_usd=one_batch * 3.5, max_batch_items=2
    )

    assert plan.covered == 6
    assert plan.covered_estimate_usd <= one_batch * 3.5
    assert plan.full_estimate_usd > one_batch * 3.5


def test_plan_line_says_how_much_the_budget_covers_and_what_full_needs():
    evidence = [_ev(i) for i in range(10)]
    one_batch = estimate_cost(evidence[:2], "SYS", "anthropic")

    plan = plan_budget(
        evidence, "SYS", "anthropic", budget_usd=one_batch * 3.5, max_batch_items=2
    )
    line = plan.line(one_batch * 3.5, rules_decided=4, order="billed cost")

    assert "10 residual candidates after rules (4)" in line
    assert "covers ~6 of 10" in line
    assert "billed cost" in line
    assert "LLM_BUDGET_USD=" in line


def test_plan_line_for_a_budget_that_covers_everything_has_no_advice():
    plan = plan_budget([_ev(0)], "SYS", "anthropic", budget_usd=5.0)

    line = plan.line(5.0, rules_decided=0, order="type risk")

    assert "covers all 1 residual candidates" in line
    assert "LLM_BUDGET_USD" not in line


EIP = "AWS::EC2::EIP"


def _ev_typed(rid, rtype, cost=None, status="ok", metrics=None, state=None):
    r = Resource(f"arn:aws:ec2:us-east-1:1:x/{rid}", rtype, "aws", "us-east-1")
    return Evidence(
        r,
        billed_cost_usd=cost,
        metrics={"ops": 0.0} if metrics is None else metrics,
        metrics_status=status,
        state=state,
    )


def test_without_billed_cost_list_price_orders_the_candidates():
    eip = _ev_typed("eip", EIP)
    nat = _ev_typed("nat", NAT)
    big = _ev_typed("vol-big", VOL, state={"size_gb": 2000, "volume_type": "gp3"})

    ranked = rank_for_triage([eip, nat, big])

    assert [e.resource.resource_type for e in ranked] == [VOL, NAT, EIP]


def test_billed_cost_beats_a_list_price_estimate():
    nat = _ev_typed("nat", NAT)
    billed = _ev_typed("vol", VOL, cost=500.0)

    assert rank_for_triage([nat, billed])[0] is billed


def test_equal_dollars_put_idle_first_then_unknown_then_active():
    active = _ev_typed("a", VOL, metrics={"ops": 900.0})
    unknown = _ev_typed("b", VOL, status="no_data", metrics={})
    idle = _ev_typed("c", VOL, metrics={"ops": 0.0})

    assert rank_for_triage([active, unknown, idle]) == [idle, unknown, active]


def test_ranking_basis_names_what_the_order_used():
    nat = _ev_typed("nat", NAT)
    plain = _ev_typed("v", VOL)

    assert ranking_basis([_ev_typed("v", VOL, cost=5.0), nat]) == "billed_cost"
    assert ranking_basis([nat, plain]) == "list_price"
    assert ranking_basis([plain]) == "type_risk"
