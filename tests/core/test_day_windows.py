"""Configurable day windows: metrics (existing), cost, and last-activity."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from adapters.aws.cloudtrail import get_last_activity
from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, ToolCall
from core.agent.loop import AgentLoop
from core.agent.prompts import build_system_prompt, build_tool_schemas
from core.config import ScanSettings

NAT = "AWS::EC2::NatGateway"


class WindowAdapter(CloudAdapter):
    max_cost_days = None

    def __init__(self):
        self.cost_days: list[int] = []

    def list_resources(self, ignore_regions=None):
        return [Resource("nat-1", NAT, "aws", "us-east-1")]

    def get_metrics(self, resource_id, resource_type, days=90):
        return MetricSummary(resource_id, resource_type, days, {"b": 1.0})

    def get_cost(self, resource_ids, days=30):
        self.cost_days.append(days)
        return {}

    def get_last_activity(self, resource_id, resource_type):
        return None


class TestSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("COST_LOOKBACK_DAYS", raising=False)
        monkeypatch.delenv("ACTIVITY_LOOKBACK_DAYS", raising=False)
        cfg = ScanSettings()
        assert cfg.cost_lookback_days == 14
        assert cfg.activity_lookback_days == 90

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("COST_LOOKBACK_DAYS", "7")
        monkeypatch.setenv("ACTIVITY_LOOKBACK_DAYS", "30")
        cfg = ScanSettings()
        assert (cfg.cost_lookback_days, cfg.activity_lookback_days) == (7, 30)

    @pytest.mark.parametrize("var", ["COST_LOOKBACK_DAYS", "ACTIVITY_LOOKBACK_DAYS"])
    @pytest.mark.parametrize("value", ["0", "-3"])
    def test_non_positive_values_are_rejected(self, monkeypatch, var, value):
        monkeypatch.setenv(var, value)
        with pytest.raises(ValidationError):
            ScanSettings()


class TestCostWindow:
    def test_prefilter_requests_the_configured_cost_window(self, monkeypatch):
        monkeypatch.setenv("COST_LOOKBACK_DAYS", "7")
        adapter = WindowAdapter()
        AgentLoop(MagicMock(spec=AIProvider), adapter)._prefilter_resources([])
        assert adapter.cost_days == [7]

    def test_model_cannot_override_the_cost_window(self, monkeypatch):
        monkeypatch.setenv("COST_LOOKBACK_DAYS", "7")
        adapter = WindowAdapter()
        AgentLoop(MagicMock(spec=AIProvider), adapter)._execute(
            ToolCall("t", "get_cost", {"resource_ids": ["nat-1"], "days": 30})
        )
        assert adapter.cost_days == [7]

    def test_scan_window_reports_the_cost_window_capped_by_the_adapter(
        self, monkeypatch
    ):
        monkeypatch.setenv("COST_LOOKBACK_DAYS", "30")
        adapter = WindowAdapter()
        adapter.max_cost_days = 14
        loop = AgentLoop(MagicMock(spec=AIProvider), adapter)
        loop._prefilter_resources([])
        assert loop.scan_window["cost_lookback_days"] == 14
        assert adapter.cost_days == [14]

    def test_scan_window_reports_uncapped_windows_as_given(self, monkeypatch):
        monkeypatch.setenv("COST_LOOKBACK_DAYS", "30")
        loop = AgentLoop(MagicMock(spec=AIProvider), WindowAdapter())
        loop._prefilter_resources([])
        assert loop.scan_window["cost_lookback_days"] == 30

    def test_aws_adapter_declares_its_resource_level_limit(self):
        from adapters.aws.adapter import AWSAdapter

        assert AWSAdapter.max_cost_days == 14

    def test_tool_schema_states_the_fixed_cost_window(self):
        schema = build_tool_schemas(lookback_days=14, cost_days=7)
        cost = next(t for t in schema if t["name"] == "get_cost")
        text = cost["description"] + str(cost["input_schema"])
        assert "7 days" in text
        assert "default: 30" not in text


class TestActivityWindow:
    def _session(self):
        client = MagicMock()
        client.lookup_events.return_value = {"Events": []}
        session = MagicMock()
        session.client.return_value = client
        return session, client

    def test_cloudtrail_uses_the_configured_window(self, monkeypatch):
        monkeypatch.setenv("ACTIVITY_LOOKBACK_DAYS", "30")
        session, client = self._session()

        get_last_activity(session, "arn:aws:ec2:us-east-1:1:instance/i-1", "t")

        kwargs = client.lookup_events.call_args.kwargs
        assert kwargs["EndTime"] - kwargs["StartTime"] == timedelta(days=30)

    def test_cloudtrail_window_is_capped_at_90_days(self, monkeypatch):
        monkeypatch.setenv("ACTIVITY_LOOKBACK_DAYS", "365")
        session, client = self._session()

        get_last_activity(session, "arn:aws:ec2:us-east-1:1:instance/i-1", "t")

        kwargs = client.lookup_events.call_args.kwargs
        assert kwargs["EndTime"] - kwargs["StartTime"] == timedelta(days=90)

    def test_scan_window_and_prompt_state_the_activity_window(self, monkeypatch):
        monkeypatch.setenv("ACTIVITY_LOOKBACK_DAYS", "30")
        loop = AgentLoop(MagicMock(spec=AIProvider), WindowAdapter())
        loop._prefilter_resources([])
        assert loop.scan_window["activity_lookback_days"] == 30

        prompt = build_system_prompt("aws", [], [], lookback_days=14, activity_days=30)
        assert "last-activity" in prompt.lower()
        assert "30 days" in prompt
