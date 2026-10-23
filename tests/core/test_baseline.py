from datetime import datetime, timezone
from unittest.mock import MagicMock

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import AgentLoop
from core.baseline import run_baseline

NAT = "AWS::EC2::NatGateway"
ALB_ARN = "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/app/web/abc"
NLB_ARN = "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/net/nlb/abc"
LB = "AWS::ElasticLoadBalancingV2::LoadBalancer"
CLB = "AWS::ElasticLoadBalancing::LoadBalancer"
ACCOUNTS = [{"id": "123456789012", "name": "t"}]


class MetricsAdapter(CloudAdapter):
    """get_metrics answers come from a dict keyed by resource id."""

    def __init__(self, resources, answers, costs=None):
        self._resources = resources
        self._answers = answers
        self._costs = costs or {}
        self.metric_calls = []

    def list_resources(self, ignore_regions=None):
        return self._resources

    def get_metrics(self, resource_id, resource_type, days=90):
        self.metric_calls.append((resource_id, days))
        answer = self._answers[resource_id]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get_cost(self, resource_ids, days=30):
        return {r: c for r, c in self._costs.items() if r in resource_ids}

    def get_last_activity(self, resource_id, resource_type):
        return datetime(2026, 4, 1, tzinfo=timezone.utc)


def _res(rid, rtype=NAT, tags=None):
    return Resource(rid, rtype, "aws", "us-east-1", tags=tags or {})


def _ok(rid, rtype, **metrics):
    return MetricSummary(rid, rtype, 14, metrics)


def _no_data(rid, rtype):
    return MetricSummary(rid, rtype, 14, {}, has_data=False)


def _run(resources, answers, costs=None, window=90):
    adapter = MetricsAdapter(resources, answers, costs)
    return run_baseline(adapter, resources, costs or {}, window_days=window), adapter


IDLE_NAT = dict(
    BytesOutToDestination=0.0, BytesInFromDestination=0.0, PacketsOutToDestination=0.0
)


def test_idle_nat_gateway_becomes_a_high_priority_rule_finding():
    result, _ = _run([_res("nat-1")], {"nat-1": _ok("nat-1", NAT, **IDLE_NAT)})

    (f,) = result.findings
    assert f.resource_id == "nat-1" and f.resource_type == NAT
    assert f.detected_by == "rule:nat-gateway-idle"
    assert f.estimated_monthly_cost == 32.85
    assert f.cost_basis == "estimated"
    assert f.priority == "high"
    assert f.confidence == "high"
    assert "route table" in f.recommendation
    assert result.evaluated_ids == {"nat-1"}


def test_nat_with_real_traffic_is_not_flagged_but_counts_as_evaluated():
    traffic = dict(IDLE_NAT, BytesOutToDestination=5e9)
    result, _ = _run([_res("nat-1")], {"nat-1": _ok("nat-1", NAT, **traffic)})

    assert result.findings == []
    assert result.evaluated_ids == {"nat-1"}


def test_missing_data_is_never_turned_into_a_finding():
    result, _ = _run(
        [_res("nat-1"), _res("nat-2")],
        {"nat-1": _no_data("nat-1", NAT), "nat-2": RuntimeError("timeout")},
    )

    assert result.findings == []
    assert result.evaluated_ids == set()  # we learned nothing about either


def test_partial_data_is_not_enough():
    partial = dict(IDLE_NAT, BytesInFromDestination=None)
    result, _ = _run([_res("nat-1")], {"nat-1": _ok("nat-1", NAT, **partial)})

    assert result.findings == []


def test_alb_with_zero_requests_is_flagged_but_nlb_is_not_evaluated():
    resources = [_res(ALB_ARN, LB), _res(NLB_ARN, LB)]
    idle = dict(RequestCount=0.0, ActiveConnectionCount=0.0)
    result, adapter = _run(resources, {ALB_ARN: _ok(ALB_ARN, LB, **idle)})

    assert [f.resource_id for f in result.findings] == [ALB_ARN]
    assert result.findings[0].detected_by == "rule:alb-no-requests"
    assert result.findings[0].estimated_monthly_cost == 16.43
    assert result.findings[0].priority == "medium"
    assert [c[0] for c in adapter.metric_calls] == [ALB_ARN]


def test_classic_elb_with_zero_requests_is_flagged():
    result, _ = _run(
        [_res("clb-1", CLB)], {"clb-1": _ok("clb-1", CLB, RequestCount=0.0)}
    )

    assert result.findings[0].detected_by == "rule:classic-elb-no-requests"
    assert result.findings[0].estimated_monthly_cost == 18.25


def test_billed_cost_replaces_the_list_price():
    result, _ = _run(
        [_res("nat-1")],
        {"nat-1": _ok("nat-1", NAT, **IDLE_NAT)},
        costs={"nat-1": 71.20},
    )

    f = result.findings[0]
    assert f.estimated_monthly_cost == 71.20
    assert f.cost_basis == "billed"


def test_short_window_caps_confidence_at_medium():
    result, _ = _run(
        [_res("nat-1")], {"nat-1": _ok("nat-1", NAT, **IDLE_NAT)}, window=14
    )
    assert result.findings[0].confidence == "medium"
    assert "14" in result.findings[0].waste_reason


def test_resource_types_without_rules_are_ignored():
    result, adapter = _run([_res("vol-1", "AWS::EC2::Volume")], {})
    assert result.findings == [] and adapter.metric_calls == []


def test_output_is_deterministic_and_ordered_by_resource_id():
    resources = [_res(f"nat-{i}") for i in (3, 1, 2)]
    answers = {r.resource_id: _ok(r.resource_id, NAT, **IDLE_NAT) for r in resources}

    first, _ = _run(resources, answers)
    second, _ = _run(list(reversed(resources)), answers)

    assert [f.resource_id for f in first.findings] == ["nat-1", "nat-2", "nat-3"]
    assert [f.resource_id for f in second.findings] == ["nat-1", "nat-2", "nat-3"]


# ---- integration with the agent loop ---------------------------------------


def _submit(findings, summary="s"):
    return AIResponse(
        "tool_use",
        None,
        [
            ToolCall(
                "t",
                "submit_findings",
                {"findings": findings, "executive_summary": summary},
            )
        ],
    )


def _model_finding(rid, rtype=NAT):
    return {
        "resource_id": rid,
        "resource_type": rtype,
        "cloud": "aws",
        "region": "us-east-1",
        "estimated_monthly_cost": 1.0,
        "waste_reason": "model says idle",
        "recommendation": "delete",
        "priority": "low",
        "metrics_summary": {},
        "tags": {},
    }


def _loop_run(resources, answers, model_findings, costs=None):
    adapter = MetricsAdapter(resources, answers, costs)
    fake_ai = MagicMock(spec=AIProvider)
    fake_ai.chat.side_effect = [_submit(model_findings)]
    loop = AgentLoop(fake_ai, adapter)
    findings, _ = loop.run("aws", [], ACCOUNTS)
    return findings, loop, fake_ai


def test_rule_findings_appear_even_if_the_model_reports_nothing():
    resources = [_res("nat-1")]
    findings, _, _ = _loop_run(
        resources, {"nat-1": _ok("nat-1", NAT, **IDLE_NAT)}, model_findings=[]
    )

    assert [f.resource_id for f in findings] == ["nat-1"]
    assert findings[0].detected_by == "rule:nat-gateway-idle"
    assert findings[0].account_id == "123456789012"


def test_rule_finding_wins_over_a_model_finding_for_the_same_resource():
    resources = [_res("nat-1"), _res("nat-2")]
    answers = {
        "nat-1": _ok("nat-1", NAT, **IDLE_NAT),
        "nat-2": _ok("nat-2", NAT, **dict(IDLE_NAT, BytesOutToDestination=9e9)),
    }
    findings, _, _ = _loop_run(
        resources, answers, [_model_finding("nat-1"), _model_finding("nat-2")]
    )

    by_id = {f.resource_id: f for f in findings}
    assert by_id["nat-1"].detected_by == "rule:nat-gateway-idle"
    assert by_id["nat-1"].estimated_monthly_cost == 32.85
    assert by_id["nat-2"].detected_by == "model"


def test_decided_resources_are_removed_from_the_ai_inventory_and_prompt_says_so():
    resources = [_res("nat-1"), _res("nat-9", "AWS::EC2::Volume")]
    answers = {"nat-1": _ok("nat-1", NAT, **IDLE_NAT)}
    _, loop, fake_ai = _loop_run(resources, answers, [])

    ids = [e["id"] for e in loop._prefiltered_payload]
    assert "nat-1" not in ids and "nat-9" in ids
    prompt = fake_ai.chat.call_args.kwargs["system_prompt"]
    assert "RULE-BASED FINDINGS" in prompt and "nat-1" in prompt


def test_coverage_counts_rule_evaluated_resources_as_analysed():
    resources = [_res("nat-1"), _res("nat-2"), _res("vol-1", "AWS::EC2::Volume")]
    answers = {
        "nat-1": _ok("nat-1", NAT, **IDLE_NAT),
        "nat-2": _ok("nat-2", NAT, **dict(IDLE_NAT, BytesOutToDestination=9e9)),
    }
    _, loop, _ = _loop_run(resources, answers, [])

    cov = loop.coverage
    assert cov.discovered == 3
    assert cov.analysed == 3  # nat-1, nat-2 by rule + vol-1 by the AI inventory
    assert cov.types[NAT].analysed == 2


def test_rules_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("ARGUS_BASELINE_RULES", "false")
    resources = [_res("nat-1")]
    findings, loop, _ = _loop_run(
        resources, {"nat-1": _ok("nat-1", NAT, **IDLE_NAT)}, []
    )

    assert findings == []
    assert [e["id"] for e in loop._prefiltered_payload] == ["nat-1"]


def test_two_runs_with_a_silent_model_give_identical_findings():
    resources = [_res(f"nat-{i}") for i in range(3)]
    answers = {r.resource_id: _ok(r.resource_id, NAT, **IDLE_NAT) for r in resources}

    first, _, _ = _loop_run(resources, answers, [])
    second, _, _ = _loop_run(resources, answers, [])

    assert [f.to_dict()["resource_id"] for f in first] == [
        f.to_dict()["resource_id"] for f in second
    ]
    assert len(first) == 3


def test_baseline_log_says_how_many_candidates_could_not_be_decided():
    from structlog.testing import capture_logs

    resources = [_res("nat-1"), _res("nat-2"), _res("nat-3")]
    answers = {
        "nat-1": _ok("nat-1", NAT, **IDLE_NAT),
        "nat-2": _no_data("nat-2", NAT),
        "nat-3": RuntimeError("timeout"),
    }

    with capture_logs() as logs:
        _run(resources, answers)

    done = next(e for e in logs if e["event"] == "baseline_complete")
    assert (done["candidates"], done["evaluated"], done["findings"]) == (3, 1, 1)
    assert done["undecided"] == 2
