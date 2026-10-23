from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import AgentLoop
from core.agent.prompts import build_system_prompt, build_tool_schemas
from core.models.finding import ResourceFinding

ACCOUNTS = [{"id": "123456789012", "name": "t"}]
NAT = "AWS::EC2::NatGateway"


class Adapter(CloudAdapter):
    """nat-nodata has no metric data; nat-zero has real data."""

    def list_resources(self, ignore_regions=None):
        return [
            Resource("nat-nodata", NAT, "aws", "us-east-1"),
            Resource("nat-zero", NAT, "aws", "us-east-1"),
        ]

    def get_metrics(self, resource_id, resource_type, days=90):
        if resource_id == "nat-nodata":
            return MetricSummary(
                resource_id, resource_type, days, {"b": None}, has_data=False
            )
        return MetricSummary(resource_id, resource_type, days, {"b": 0.0})

    def get_cost(self, resource_ids, days=30):
        return {}

    def get_last_activity(self, resource_id, resource_type):
        return datetime(2026, 4, 1, tzinfo=timezone.utc)


def _finding(rid, confidence="high", reason="zero bytes over 90 days"):
    f = {
        "resource_id": rid,
        "resource_type": NAT,
        "cloud": "aws",
        "region": "us-east-1",
        "estimated_monthly_cost": 30.0,
        "waste_reason": reason,
        "recommendation": "delete",
        "priority": "high",
        "metrics_summary": {},
        "tags": {},
    }
    if confidence is not None:
        f["confidence"] = confidence
    return f


def _tool(name, args, tid):
    return AIResponse("tool_use", None, [ToolCall(tid, name, args)])


def _run(findings, window_days=90, monkeypatch=None):
    if monkeypatch:
        monkeypatch.setenv("METRICS_LOOKBACK_DAYS", str(window_days))
    fake_ai = MagicMock(spec=AIProvider)
    fake_ai.chat.side_effect = [
        _tool(
            "get_metrics",
            {"resource_id": "nat-nodata", "resource_type": NAT},
            "t1",
        ),
        _tool(
            "get_metrics",
            {"resource_id": "nat-zero", "resource_type": NAT},
            "t2",
        ),
        _tool(
            "submit_findings",
            {"findings": findings, "executive_summary": "s"},
            "t3",
        ),
    ]
    out, _ = AgentLoop(fake_ai, Adapter()).run("aws", [], ACCOUNTS)
    return {f.resource_id: f for f in out}


def test_no_data_finding_forced_to_low_confidence():
    by_id = _run([_finding("nat-nodata", "high"), _finding("nat-zero", "high")])
    assert by_id["nat-nodata"].confidence == "low"
    assert by_id["nat-zero"].confidence == "high"


def test_window_under_90_caps_confidence_at_medium(monkeypatch):
    by_id = _run(
        [_finding("nat-zero", "high")], window_days=14, monkeypatch=monkeypatch
    )
    assert by_id["nat-zero"].confidence == "medium"


def test_low_stays_low_under_short_window(monkeypatch):
    by_id = _run([_finding("nat-zero", "low")], window_days=14, monkeypatch=monkeypatch)
    assert by_id["nat-zero"].confidence == "low"


@pytest.mark.parametrize("given", [None, "bogus", "HIGH "])
def test_missing_or_invalid_confidence_defaults_to_medium_or_normalised(given):
    by_id = _run([_finding("nat-zero", given)])
    expected = "high" if given == "HIGH " else "medium"
    assert by_id["nat-zero"].confidence == expected


def test_confidence_round_trips_through_dict():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    f = ResourceFinding.from_dict({**_finding("x", "low")}, now)
    assert f.confidence == "low"
    assert f.to_dict()["confidence"] == "low"


def test_prompt_and_schema_describe_confidence_and_no_data_rule():
    prompt = build_system_prompt("aws", [], ACCOUNTS)
    assert "status" in prompt and "no metric data" in prompt
    submit = next(t for t in build_tool_schemas() if t["name"] == "submit_findings")
    item = submit["input_schema"]["properties"]["findings"]["items"]["properties"]
    assert item["confidence"]["enum"] == ["low", "medium", "high"]


def test_confidence_shown_in_html():
    from core.reports.generator import build_report
    from core.reports.html import build_html_report

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    f = ResourceFinding.from_dict(_finding("x", "low"), now)
    html = build_html_report(build_report([f], cloud="aws", executive_summary="s"))
    assert "confidence: low" in html


def test_exception_in_get_metrics_forces_low_confidence():
    class Boom(Adapter):
        def get_metrics(self, resource_id, resource_type, days=90):
            raise RuntimeError("read timeout")

    fake_ai = MagicMock(spec=AIProvider)
    fake_ai.chat.side_effect = [
        _tool("get_metrics", {"resource_id": "nat-zero", "resource_type": NAT}, "t1"),
        _tool(
            "submit_findings",
            {"findings": [_finding("nat-zero", "high")], "executive_summary": "s"},
            "t2",
        ),
    ]

    out, _ = AgentLoop(fake_ai, Boom()).run("aws", [], ACCOUNTS)

    assert out[0].confidence == "low"


def test_requested_id_is_tracked_even_if_adapter_returns_a_different_id():
    class Rewriting(Adapter):
        def get_metrics(self, resource_id, resource_type, days=90):
            return MetricSummary("short-id", resource_type, days, {}, has_data=False)

    fake_ai = MagicMock(spec=AIProvider)
    fake_ai.chat.side_effect = [
        _tool("get_metrics", {"resource_id": "nat-zero", "resource_type": NAT}, "t1"),
        _tool(
            "submit_findings",
            {"findings": [_finding("nat-zero", "high")], "executive_summary": "s"},
            "t2",
        ),
    ]

    out, _ = AgentLoop(fake_ai, Rewriting()).run("aws", [], ACCOUNTS)

    assert out[0].confidence == "low"
