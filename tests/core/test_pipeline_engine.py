"""End to end: AgentLoop.run with ARGUS_ENGINE=pipeline."""

from unittest.mock import MagicMock

import pytest

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import AgentLoop
from core.errors import AgentDidNotSubmitError

VOL = "AWS::EC2::Volume"
NAT = "AWS::EC2::NatGateway"
ACCOUNTS = [{"id": "123456789012", "name": "t"}]
IDLE_NAT = dict(
    BytesOutToDestination=0.0, BytesInFromDestination=0.0, PacketsOutToDestination=0.0
)


@pytest.fixture(autouse=True)
def _pipeline(monkeypatch):
    monkeypatch.setenv("ARGUS_ENGINE", "pipeline")


class Adapter(CloudAdapter):
    def __init__(self, resources, metrics=None, costs=None):
        self._resources = resources
        self._metrics = metrics or {}
        self._costs = costs or {}
        self.list_calls = 0

    def list_resources(self, ignore_regions=None):
        self.list_calls += 1
        return self._resources

    def get_metrics(self, resource_id, resource_type, days=90):
        return self._metrics.get(
            resource_id, MetricSummary(resource_id, resource_type, days, {}, False)
        )

    def get_cost(self, resource_ids, days=30):
        return {k: v for k, v in self._costs.items() if k in resource_ids}

    def get_last_activity(self, resource_id, resource_type):
        return None


def _vol(n, tags=None):
    return Resource(f"vol-{n:03d}", VOL, "aws", "us-east-1", tags=tags or {})


def _ok(rid, rtype=VOL, **m):
    return MetricSummary(rid, rtype, 14, m or {"ops": 0.0})


def _report(*findings, in_tok=2000, out_tok=200):
    return AIResponse(
        "tool_use",
        None,
        [ToolCall("t", "report_findings", {"findings": list(findings)})],
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def _f(i, **kw):
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


def _run(adapter, responses):
    ai = MagicMock(spec=AIProvider)
    ai.chat.side_effect = responses
    loop = AgentLoop(ai, adapter)
    findings, summary = loop.run("aws", [], ACCOUNTS)
    return findings, summary, loop, ai


def _index_of(ai, rid_suffix):
    text = ai.chat.call_args_list[0].args[0][0].text
    for line in text.splitlines():
        if f'"id":"{rid_suffix}"' in line:
            return int(line.split('"i":')[1].split(",")[0])
    raise AssertionError(rid_suffix)


def test_findings_are_built_from_the_resource_not_from_model_prose():
    res = [_vol(0, tags={"team": "data"}), _vol(1)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})
    ai = MagicMock(spec=AIProvider)
    ai.chat.side_effect = lambda messages, tools, system_prompt=None: _report(
        _f(_index_of_in(messages, "vol-000"))
    )
    loop = AgentLoop(ai, adapter)

    findings, _ = loop.run("aws", [], ACCOUNTS)

    (f,) = findings
    assert f.resource_id == "vol-000" and f.resource_type == VOL
    assert f.region == "us-east-1" and f.cloud == "aws"
    assert f.tags == {"team": "data"}
    assert f.detected_by == "model" and f.cost_basis == "model_estimate"
    assert f.estimated_monthly_cost == 8.0
    assert f.account_id == "123456789012"
    assert f.metrics_summary["metrics"] == {"ops": 0.0}
    assert f.metrics_summary["metrics_status"] == "ok"


def _index_of_in(messages, rid):
    for line in messages[0].text.splitlines():
        if f'"id":"{rid}"' in line:
            return int(line.split('"i":')[1].split(",")[0])
    raise AssertionError(rid)


def test_billed_cost_beats_the_models_guess():
    res = [_vol(0)]
    adapter = Adapter(res, metrics={"vol-000": _ok("vol-000")}, costs={"vol-000": 21.5})

    findings, _, _, _ = _run(adapter, [_report(_f(0, estimated_monthly_cost=999))])

    assert findings[0].estimated_monthly_cost == 21.5
    assert findings[0].cost_basis == "billed"


def test_unavailable_evidence_forces_low_confidence():
    res = [_vol(0)]  # no metrics at all
    adapter = Adapter(res)

    findings, _, _, _ = _run(adapter, [_report(_f(0, confidence="high"))])

    assert findings[0].confidence == "low"


def test_rule_findings_win_and_resources_they_decided_are_not_sent_to_the_model():
    nat = Resource("nat-1", NAT, "aws", "us-east-1")
    res = [nat, _vol(0)]
    adapter = Adapter(
        res,
        metrics={
            "nat-1": MetricSummary("nat-1", NAT, 14, IDLE_NAT),
            "vol-000": _ok("vol-000"),
        },
    )

    findings, _, _, ai = _run(adapter, [_report()])

    assert {f.resource_id: f.detected_by for f in findings} == {
        "nat-1": "rule:nat-gateway-idle"
    }
    sent = ai.chat.call_args_list[0].args[0][0].text
    assert "nat-1" not in sent and "vol-000" in sent


def test_one_model_call_covers_a_hundred_resources_and_history_never_grows():
    res = [_vol(i) for i in range(100)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})

    _, _, loop, ai = _run(adapter, [_report()] * 5)

    assert 1 <= ai.chat.call_count <= 3
    assert all(len(c.args[0]) == 1 for c in ai.chat.call_args_list)
    assert loop.coverage.analysed == 100 and loop.coverage.dropped == 0


def test_explicit_cap_is_honoured_and_reported_as_the_reason():
    res = [_vol(i) for i in range(20)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})
    import os

    os.environ["MAX_RESOURCES_PER_SCAN"] = "5"
    try:
        from core.config import clear_settings_cache

        clear_settings_cache()
        _, _, loop, _ = _run(adapter, [_report()])
    finally:
        del os.environ["MAX_RESOURCES_PER_SCAN"]

    cov = loop.coverage
    assert (cov.discovered, cov.analysed, cov.dropped) == (20, 5, 15)
    assert cov.skipped_by_reason == {"cap": 15}
    assert cov.stop_reason == "cap"


def test_budget_stop_keeps_findings_and_is_reported_honestly(monkeypatch):
    monkeypatch.setenv("LLM_BUDGET_USD", "0.5")
    res = [_vol(i) for i in range(4)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})
    monkeypatch.setenv("ARGUS_TRIAGE_BATCH_ITEMS", "2")

    findings, summary, loop, ai = _run(
        adapter, [_report(_f(0), in_tok=200_000, out_tok=1000)] * 4
    )

    assert [f.resource_id for f in findings] == ["vol-000"]
    assert summary.startswith("Scan aborted: LLM budget")
    assert "findings found so far are included" in summary
    assert loop.coverage.stop_reason == "budget"
    assert loop.coverage.skipped_by_reason == {"budget": 2}
    assert loop.coverage.analysed == 2


def test_empty_inventory_makes_no_model_call():
    findings, summary, loop, ai = _run(Adapter([]), [])

    assert findings == []
    ai.chat.assert_not_called()
    assert "No resources" in summary
    assert loop.coverage.discovered == 0


def test_summary_is_deterministic_and_labels_estimates():
    res = [_vol(0), _vol(1)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})

    _, s1, _, _ = _run(adapter, [_report(_f(0), _f(1, priority="low"))])
    _, s2, _, _ = _run(adapter, [_report(_f(0), _f(1, priority="low"))])

    assert s1 == s2
    assert "2 resources" in s1 and "1 high" in s1 and "1 low" in s1
    assert "not billed" in s1
    assert "Analysed 2 of 2" in s1


def test_summary_calls_out_findings_that_need_human_review():
    res = [
        Resource(
            "vol-000", VOL, "aws", "us-east-1", name="PROD - Trading - DO NOT TOUCH"
        ),
        _vol(1),
    ]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})

    _, summary, _, _ = _run(adapter, [_report(_f(0), _f(1))])

    assert "estimate only, not billed, unverified" in summary
    assert "1 finding that need human review" in summary


def test_two_runs_return_identical_findings():
    res = [_vol(i) for i in range(6)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})
    reply = lambda: _report(_f(2), _f(4, priority="medium"))  # noqa: E731

    a, _, _, _ = _run(adapter, [reply()])
    b, _, _, _ = _run(adapter, [reply()])

    assert [f.to_dict()["resource_id"] for f in a] == [
        f.to_dict()["resource_id"] for f in b
    ]


def test_model_that_never_reports_fails_loudly():
    adapter = Adapter([_vol(0)], metrics={"vol-000": _ok("vol-000")})
    none = AIResponse("end_turn", "fine", [])

    with pytest.raises(AgentDidNotSubmitError):
        _run(adapter, [none, none])


def test_the_react_engine_is_still_available(monkeypatch):
    monkeypatch.setenv("ARGUS_ENGINE", "react")
    ai = MagicMock(spec=AIProvider)
    ai.chat.side_effect = [
        AIResponse(
            "tool_use",
            None,
            [
                ToolCall(
                    "t",
                    "submit_findings",
                    {"findings": [], "executive_summary": "react ran"},
                )
            ],
        )
    ]

    _, summary = AgentLoop(ai, Adapter([_vol(0)])).run("aws", [], ACCOUNTS)

    assert summary == "react ran"


def test_free_config_objects_skipped_by_the_adapter_are_reported():
    class Filtering(Adapter):
        filtered_by_type = {"ec2:subnet": 3, "iam:role": 4}

    res = [_vol(0)]
    adapter = Filtering(res, metrics={"vol-000": _ok("vol-000")})

    _, summary, loop, _ = _run(adapter, [_report()])

    assert loop.coverage.free_config_skipped == 7
    assert loop.coverage.to_dict()["free_config_skipped"] == 7
    assert "7 free configuration objects" in summary


def test_metrics_lost_to_throttling_are_counted_and_stated():
    res = [_vol(0), _vol(1), _vol(2)]
    throttled = {
        rid: MetricSummary(
            rid,
            VOL,
            14,
            {},
            False,
            status="error",
            error="Throttling: Rate exceeded",
        )
        for rid in ("vol-000", "vol-001")
    }
    denied = MetricSummary(
        "vol-002", VOL, 14, {}, False, status="error", error="AccessDenied: no"
    )
    adapter = Adapter(res, metrics={**throttled, "vol-002": denied})

    _, summary, loop, _ = _run(adapter, [_report()])

    assert loop.coverage.metrics_lost_to_throttling == 2
    assert loop.coverage.to_dict()["metrics_lost_to_throttling"] == 2
    assert "2 resources" in summary and "throttl" in summary.lower()


def test_configuration_state_collected_for_rules_reaches_the_model():
    class Stateful(Adapter):
        def collect_state(self, resources):
            return {
                r.resource_id: {
                    "kind": "ebs_volume",
                    "state": "in-use",
                    "size_gb": 40,
                    "volume_type": "gp3",
                    "attached_to": ["i-1"],
                }
                for r in resources
            }

    res = [_vol(0)]
    adapter = Stateful(res, metrics={"vol-000": _ok("vol-000")})

    _, _, _, ai = _run(adapter, [_report()])

    sent = ai.chat.call_args_list[0].args[0][0].text
    assert '"st":{"state":"in-use"' in sent


def test_scan_window_records_estimated_against_actual_tokens_per_call():
    res = [_vol(0), _vol(1)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})

    _, _, loop, _ = _run(adapter, [_report(in_tok=1234, out_tok=56)])

    cal = loop.scan_window["llm_calibration"]
    assert cal["calls"] == 1
    assert cal["actual_input_tokens"] == 1234 and cal["actual_output_tokens"] == 56
    assert cal["estimated_input_tokens"] > 0
    assert cal["per_call"][0]["items"] == 2


def test_coverage_is_reported_per_stage():
    res = [_vol(0), _vol(1), _vol(2)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})

    _, _, loop, _ = _run(adapter, [_report(_f(0))])

    stages = loop.coverage.to_dict()["stages"]
    assert stages["rules"]["findings"] == 0
    assert stages["gate"] == {"mode": "off", "settled": 0}
    assert stages["model"]["candidates"] == 3
    assert stages["model"]["analysed"] == 3
    assert stages["model"]["skipped"] == 0
    assert stages["model"]["stop_reason"] is None


def test_the_plan_is_recorded_before_any_spend():
    res = [_vol(0), _vol(1)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})

    _, _, loop, _ = _run(adapter, [_report()])

    plan = loop.scan_window["llm_plan"]
    assert plan["candidates"] == 2 and plan["covered"] == 2
    assert plan["full_estimate_usd"] > 0
    assert plan["order"] == "type_risk"
    assert "residual candidates" in plan["line"]


def test_strict_coverage_stops_before_any_model_call_when_the_budget_is_short(
    monkeypatch,
):
    from core.errors import StrictCoverageError

    monkeypatch.setenv("LLM_BUDGET_USD", "0.0001")
    monkeypatch.setenv("STRICT_COVERAGE", "true")
    res = [_vol(i) for i in range(5)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})
    ai = MagicMock(spec=AIProvider)

    with pytest.raises(StrictCoverageError, match="covers ~"):
        AgentLoop(ai, adapter).run("aws", [], ACCOUNTS)

    ai.chat.assert_not_called()


def test_a_budget_stop_leads_with_the_model_denominator_and_a_lower_bound(monkeypatch):
    monkeypatch.setenv("LLM_BUDGET_USD", "0.5")
    monkeypatch.setenv("ARGUS_TRIAGE_BATCH_ITEMS", "2")
    res = [_vol(i) for i in range(4)]
    adapter = Adapter(res, metrics={r.resource_id: _ok(r.resource_id) for r in res})

    _, summary, _, _ = _run(adapter, [_report(_f(0), in_tok=200_000, out_tok=1000)] * 4)

    assert "Model reviewed 2 of 4 candidates" in summary
    assert "lower bound" in summary


def test_scan_window_says_where_the_tags_came_from():
    class Tagged(Adapter):
        tags_source = "tagging_api"

    _, _, loop, _ = _run(
        Tagged([_vol(0)], metrics={"vol-000": _ok("vol-000")}), [_report()]
    )

    assert loop.scan_window["tags_source"] == "tagging_api"


def test_the_pipeline_works_for_other_clouds_too():
    class Gcp(Adapter):
        pass

    inst = Resource(
        "//compute.googleapis.com/projects/p/zones/z/instances/vm1",
        "compute.googleapis.com/Instance",
        "gcp",
        "us-central1-a",
    )
    adapter = Gcp(
        [inst],
        metrics={
            inst.resource_id: MetricSummary(
                inst.resource_id, inst.resource_type, 14, {"cpu": 0.1}
            )
        },
    )
    ai = MagicMock(spec=AIProvider)
    ai.chat.side_effect = [_report(_f(0, estimated_monthly_cost=40.0))]

    findings, summary = AgentLoop(ai, adapter).run(
        "gcp", [], [{"id": "p", "name": "p"}]
    )

    assert [f.cloud for f in findings] == ["gcp"]
    assert findings[0].resource_type == "compute.googleapis.com/Instance"
    assert "GCP" in ai.chat.call_args.kwargs["system_prompt"]
