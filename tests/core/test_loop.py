from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, Message, Tool, ToolCall, ToolResult
from core.agent.loop import AgentLoop, MAX_ITERATIONS, _compress_resource
from core.models.finding import ResourceFinding


IGNORE_REGIONS: list[str] = []
ACCOUNTS = [{"id": "123456789012", "name": "test-account"}]

# ------------------------------------------------------------------
# Minimal fakes (no external dependencies)
# ------------------------------------------------------------------

class FakeCloudAdapter(CloudAdapter):
    """Returns predictable data; never calls real AWS."""

    def list_resources(self, ignore_regions=None):
        return [
            Resource(
                resource_id="nat-0abc123",
                resource_type="AWS::EC2::NatGateway",
                cloud="aws",
                region="us-east-1",
                tags={},
            )
        ]

    def get_metrics(self, resource_id, resource_type, days=90):
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={"bytes_out_total": 847},
        )

    def get_cost(self, resource_ids, days=30):
        return {rid: 32.50 for rid in resource_ids}

    def get_last_activity(self, resource_id, resource_type):
        return datetime(2026, 4, 1, tzinfo=timezone.utc)


def _make_tool_use_response(tool_name: str, tool_id: str, arguments: dict) -> AIResponse:
    return AIResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=arguments)],
    )


def _make_submit_response(findings: list, summary: str) -> AIResponse:
    return AIResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[
            ToolCall(
                id="toolu_final",
                name="submit_findings",
                arguments={
                    "findings": findings,
                    "executive_summary": summary,
                },
            )
        ],
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestAgentLoopHappyPath:
    def test_returns_findings_and_summary(self):
        finding_data = {
            "resource_id": "nat-0abc123",
            "resource_type": "AWS::EC2::NatGateway",
            "cloud": "aws",
            "region": "us-east-1",
            "estimated_monthly_cost": 32.50,
            "waste_reason": "847 bytes transferred in 14 days",
            "recommendation": "Delete the NAT Gateway",
            "priority": "high",
            "metrics_summary": {"bytes_out_total": 847},
            "tags": {},
        }
        summary = "Found 1 idle NAT Gateway costing $32.50/month."

        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.side_effect = [
            _make_tool_use_response("list_resources", "toolu_1", {"ignore_regions": []}),
            _make_submit_response([finding_data], summary),
        ]

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        findings, exec_summary = loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        assert len(findings) == 1
        assert findings[0].resource_id == "nat-0abc123"
        assert findings[0].estimated_monthly_cost == 32.50
        assert findings[0].priority == "high"
        assert exec_summary == summary

    def test_findings_sorted_by_cost_descending(self):
        raw = [
            {
                "resource_id": "cheap-001",
                "resource_type": "AWS::EC2::Volume",
                "cloud": "aws", "region": "us-east-1",
                "estimated_monthly_cost": 5.0,
                "waste_reason": "unattached", "recommendation": "delete",
                "priority": "low", "metrics_summary": {}, "tags": {},
            },
            {
                "resource_id": "expensive-001",
                "resource_type": "AWS::EC2::NatGateway",
                "cloud": "aws", "region": "us-east-1",
                "estimated_monthly_cost": 94.0,
                "waste_reason": "no traffic", "recommendation": "delete",
                "priority": "high", "metrics_summary": {}, "tags": {},
            },
        ]

        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.return_value = _make_submit_response(raw, "Two findings.")

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        findings, _ = loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        assert findings[0].resource_id == "expensive-001"
        assert findings[1].resource_id == "cheap-001"

    def test_tool_dispatch_list_resources(self):
        """
        list_resources is called once during Phase 0 pre-filter (not again when
        the AI calls the tool — the cached payload is returned instead).
        """
        adapter = FakeCloudAdapter()
        adapter.list_resources = MagicMock(wraps=adapter.list_resources)

        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.side_effect = [
            _make_tool_use_response("list_resources", "toolu_1", {"ignore_regions": []}),
            _make_submit_response([], "No findings."),
        ]

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=adapter)
        loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        # Called exactly once during pre-filter (Phase 0), with None because
        # empty list is normalised to None inside _prefilter_resources.
        adapter.list_resources.assert_called_once_with(ignore_regions=None)

    def test_tool_dispatch_get_cost(self):
        """
        get_cost is called once during Phase 0 pre-filter AND once more when
        the AI explicitly calls it. Both calls must reach the adapter.
        """
        adapter = FakeCloudAdapter()
        adapter.get_cost = MagicMock(wraps=adapter.get_cost)

        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.side_effect = [
            _make_tool_use_response(
                "get_cost", "toolu_2",
                {"resource_ids": ["nat-0abc123", "alb-xyz"], "days": 30}
            ),
            _make_submit_response([], "No findings."),
        ]

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=adapter)
        loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        # First call: Phase 0 pre-filter (all resource IDs from list_resources)
        # Second call: AI-requested get_cost with its chosen IDs
        assert adapter.get_cost.call_count == 2
        # Verify the AI-requested call went through correctly
        adapter.get_cost.assert_called_with(
            resource_ids=["nat-0abc123", "alb-xyz"], days=30
        )

    def test_empty_findings_when_nothing_idle(self):
        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.return_value = _make_submit_response([], "No idle resources found.")

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        findings, summary = loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        assert findings == []
        assert "No idle" in summary


class TestAgentLoopEdgeCases:
    def test_end_turn_without_findings_returns_empty(self):
        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.return_value = AIResponse(
            stop_reason="end_turn",
            text="I could not determine idle resources.",
            tool_calls=[],
        )

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        findings, summary = loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        assert findings == []
        assert "could not" in summary

    def test_unknown_tool_returns_error_result(self):
        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.side_effect = [
            _make_tool_use_response("nonexistent_tool", "toolu_bad", {}),
            _make_submit_response([], "Done."),
        ]

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        # Should not raise — error is passed back to AI as a tool result
        findings, _ = loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)
        assert findings == []

    def test_max_iterations_raises(self):
        fake_ai = MagicMock(spec=AIProvider)
        # Always returns another tool call, never submit_findings
        fake_ai.chat.return_value = _make_tool_use_response(
            "list_resources", "toolu_loop", {"ignore_regions": []}
        )

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        with pytest.raises(RuntimeError, match="exceeded"):
            loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        assert fake_ai.chat.call_count == MAX_ITERATIONS


class TestCompressResource:
    def _full(self, **overrides) -> dict:
        base = {
            "resource_id": "arn:aws:ec2:us-east-1:123:instance/i-0abc",
            "resource_type": "AWS::EC2::Instance",
            "cloud": "aws",
            "region": "us-east-1",
            "name": "web-01",
            "tags": {"Env": "prod", "Name": "web-01"},
        }
        return {**base, **overrides}

    def test_shortens_keys(self):
        out = _compress_resource(self._full())
        assert "id" in out
        assert "resource_id" not in out
        assert "type" in out
        assert "resource_type" not in out

    def test_omits_cloud_field(self):
        out = _compress_resource(self._full())
        assert "cloud" not in out

    def test_omits_name_when_none(self):
        out = _compress_resource(self._full(name=None))
        assert "name" not in out

    def test_omits_tags_when_empty(self):
        out = _compress_resource(self._full(tags={}))
        assert "tags" not in out

    def test_keeps_tags_when_present(self):
        out = _compress_resource(self._full(tags={"Owner": "alice"}))
        assert out["tags"] == {"Owner": "alice"}

    def test_preserves_id_type_region(self):
        out = _compress_resource(self._full())
        assert out["id"] == "arn:aws:ec2:us-east-1:123:instance/i-0abc"
        assert out["type"] == "AWS::EC2::Instance"
        assert out["region"] == "us-east-1"
