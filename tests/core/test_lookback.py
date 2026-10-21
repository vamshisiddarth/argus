import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import AgentLoop
from core.agent.prompts import build_system_prompt, build_tool_schemas
from core.models.finding import ResourceFinding

ACCOUNTS = [{"id": "123456789012", "name": "t"}]
NAT = "AWS::EC2::NatGateway"


class RecordingAdapter(CloudAdapter):
    def __init__(self, costs=None):
        self.metrics_calls: list[int] = []
        self._costs = costs if costs is not None else {}

    def list_resources(self, ignore_regions=None):
        return [
            Resource("nat-1", NAT, "aws", "us-east-1"),
            Resource("nat-2", NAT, "aws", "us-east-1"),
        ]

    def get_metrics(self, resource_id, resource_type, days=90):
        self.metrics_calls.append(days)
        return MetricSummary(resource_id, resource_type, days, {"x": 1})

    def get_cost(self, resource_ids, days=30):
        return {rid: c for rid, c in self._costs.items() if rid in resource_ids}

    def get_last_activity(self, resource_id, resource_type):
        return datetime(2026, 4, 1, tzinfo=timezone.utc)


def _tool(name, args, tid="t1"):
    return AIResponse(
        stop_reason="tool_use", text=None, tool_calls=[ToolCall(tid, name, args)]
    )


def _loop(adapter):
    return AgentLoop(ai_provider=MagicMock(spec=AIProvider), cloud_adapter=adapter)


def test_loop_forces_configured_window_on_get_metrics(monkeypatch):
    monkeypatch.setenv("METRICS_LOOKBACK_DAYS", "14")
    adapter = RecordingAdapter()

    _loop(adapter)._execute(
        ToolCall(
            "t1",
            "get_metrics",
            {"resource_id": "nat-1", "resource_type": NAT, "days": 90},
        )
    )

    assert adapter.metrics_calls == [14]


def test_loop_fills_days_when_model_omits_it(monkeypatch):
    monkeypatch.setenv("METRICS_LOOKBACK_DAYS", "30")
    adapter = RecordingAdapter()

    _loop(adapter)._execute(
        ToolCall("t1", "get_metrics", {"resource_id": "nat-1", "resource_type": NAT})
    )

    assert adapter.metrics_calls == [30]


def test_prompt_contains_configured_window_and_no_hardcoded_90():
    prompt = build_system_prompt("aws", [], ACCOUNTS, lookback_days=14)
    schema = json.dumps(build_tool_schemas(lookback_days=14))

    assert "past 14 days" in prompt
    for banned in ("Never set below 90", "Do NOT pass a days value less than 90"):
        assert banned not in prompt + schema
    assert "90 days" not in prompt
    assert "90-day" not in prompt
    assert '"default": 90' not in schema
    assert "14" in schema


def test_prompt_warns_when_window_below_90():
    short = build_system_prompt("aws", [], ACCOUNTS, lookback_days=14)
    full = build_system_prompt("aws", [], ACCOUNTS, lookback_days=90)

    assert "SHORT WINDOW" in short
    assert "14-day window" in short
    assert "SHORT WINDOW" not in full


def test_scan_window_reports_real_window_and_cost_basis(monkeypatch):
    monkeypatch.setenv("METRICS_LOOKBACK_DAYS", "14")
    loop = _loop(RecordingAdapter(costs={"nat-1": 32.5}))
    loop._prefilter_resources([])
    assert loop.scan_window == {
        "metrics_lookback_days": 14,
        "cost_lookback_days": 30,
        "cost_basis": "billed",
    }


def test_scan_window_cost_basis_unavailable_when_costs_empty():
    loop = _loop(RecordingAdapter(costs={}))
    loop._prefilter_resources([])
    assert loop.scan_window["cost_basis"] == "unavailable"


def test_findings_are_labelled_billed_or_estimated():
    adapter = RecordingAdapter(costs={"nat-1": 32.5})
    fake_ai = MagicMock(spec=AIProvider)
    finding = lambda rid: {  # noqa: E731
        "resource_id": rid,
        "resource_type": NAT,
        "cloud": "aws",
        "region": "us-east-1",
        "estimated_monthly_cost": 30.0,
        "waste_reason": "idle",
        "recommendation": "delete",
        "priority": "high",
        "metrics_summary": {},
        "tags": {},
    }
    fake_ai.chat.return_value = _tool(
        "submit_findings",
        {"findings": [finding("nat-1"), finding("nat-2")], "executive_summary": "s"},
    )

    findings, _ = AgentLoop(fake_ai, adapter).run("aws", [], ACCOUNTS)

    basis = {f.resource_id: f.cost_basis for f in findings}
    assert basis == {"nat-1": "billed", "nat-2": "estimated"}
    assert findings[0].to_dict()["cost_basis"] in ("billed", "estimated")


def test_finding_cost_basis_defaults_to_none_and_round_trips():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    f = ResourceFinding.from_dict(
        {
            "resource_id": "x",
            "resource_type": NAT,
            "cloud": "aws",
            "region": "r",
            "estimated_monthly_cost": 1,
            "waste_reason": "w",
            "recommendation": "r",
            "priority": "low",
            "cost_basis": "billed",
        },
        now,
    )
    assert f.cost_basis == "billed"
    assert f.to_dict()["cost_basis"] == "billed"
