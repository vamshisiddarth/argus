"""
Failing-first regression tests for the trust issues in HANDOFF_user_feedback.md.

These describe behaviour the agent loop does NOT have yet (v0.6.1):
  #2  cap keeps the "top by cost", which is arbitrary when cost data is empty
  #4  end_turn without submit_findings is returned as a successful empty scan
  #5  a metric with no data is handed to the model as if it were just a number

Expected to FAIL until the fixes land. Assertions on the exact exception type
(#4) and on the wording of the no-data notice (#5) are provisional; adjust them
to the design once it is agreed.
"""

import json
from collections import Counter
from unittest.mock import MagicMock

import pytest

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import AgentLoop

IGNORE_REGIONS: list[str] = []
ACCOUNTS = [{"id": "123456789012", "name": "test-account"}]

_TYPES = ["AWS::EC2::NatGateway", "AWS::EC2::Volume", "AWS::RDS::DBInstance"]


class NoCostAdapter(CloudAdapter):
    """12 resources grouped by type (4 each); Cost Explorer returns nothing."""

    def list_resources(self, ignore_regions=None):
        return [
            Resource(
                resource_id=f"{rtype.split('::')[-1].lower()}-{i}",
                resource_type=rtype,
                cloud="aws",
                region="us-east-1",
                tags={},
            )
            for rtype in _TYPES
            for i in range(4)
        ]

    def get_metrics(self, resource_id, resource_type, days=90):
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={"bytes_out_total": None},
            has_data=False,
        )

    def get_cost(self, resource_ids, days=30):
        return {}

    def get_last_activity(self, resource_id, resource_type):
        return None


def _tool_use(name: str, tool_id: str, arguments: dict) -> AIResponse:
    return AIResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tool_id, name=name, arguments=arguments)],
    )


def _submit(findings: list, summary: str) -> AIResponse:
    return _tool_use(
        "submit_findings",
        "toolu_final",
        {"findings": findings, "executive_summary": summary},
    )


def _end_turn(text: str) -> AIResponse:
    return AIResponse(stop_reason="end_turn", text=text, tool_calls=[])


class TestSelectionWithoutCostData:
    """#2: with no cost data the cap must not silently drop whole resource types."""

    def test_every_resource_type_survives_the_cap(self, monkeypatch):
        monkeypatch.setenv("MAX_RESOURCES_PER_SCAN", "6")  # 12 discovered, keep 6

        loop = AgentLoop(
            ai_provider=MagicMock(spec=AIProvider), cloud_adapter=NoCostAdapter()
        )
        payload = loop._prefilter_resources(IGNORE_REGIONS)

        assert len(payload) == 6
        # The compressed payload shortens resource_type to "type".
        kept = Counter(entry["type"] for entry in payload)
        assert set(kept) == set(
            _TYPES
        ), f"types dropped by the cap: {set(_TYPES) - set(kept)}"


class TestEmptyResultIsNotSuccess:
    """#4: the model stopping without submit_findings must not exit as a clean scan."""

    def test_end_turn_without_submit_fails_after_one_retry(self):
        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.return_value = _end_turn("Found ~9 idle resource groups: ...")

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=NoCostAdapter())
        with pytest.raises(RuntimeError):
            loop.run(cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS)

        # exactly one re-prompt, not a full re-run
        assert fake_ai.chat.call_count == 2

    def test_retry_that_submits_findings_succeeds(self):
        finding = {
            "resource_id": "natgateway-0",
            "resource_type": "AWS::EC2::NatGateway",
            "cloud": "aws",
            "region": "us-east-1",
            "estimated_monthly_cost": 32.5,
            "waste_reason": "idle",
            "recommendation": "Delete",
            "priority": "high",
            "metrics_summary": {},
            "tags": {},
        }
        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.side_effect = [
            _end_turn("Found 1 idle NAT Gateway."),
            _submit([finding], "Found 1 idle NAT Gateway."),
        ]

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=NoCostAdapter())
        findings, summary = loop.run(
            cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS
        )

        assert [f.resource_id for f in findings] == ["natgateway-0"]
        assert fake_ai.chat.call_count == 2


class TestNoDataIsNotZero:
    """#5: the model must be told, in the tool result, that missing data is not zero."""

    def test_get_metrics_result_flags_unavailable_data(self):
        loop = AgentLoop(
            ai_provider=MagicMock(spec=AIProvider), cloud_adapter=NoCostAdapter()
        )

        content, is_error = loop._execute(
            ToolCall(
                id="t1",
                name="get_metrics",
                arguments={
                    "resource_id": "natgateway-0",
                    "resource_type": "AWS::EC2::NatGateway",
                    "days": 14,
                },
            )
        )

        assert is_error is False
        result = json.loads(content)
        assert result["has_data"] is False
        # Provisional wording: some explicit signal beyond the bare boolean.
        assert "unavailable" in content.lower()
