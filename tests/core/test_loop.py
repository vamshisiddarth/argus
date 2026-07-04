from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import (
    _ALLOWED_TOOLS,
    _MUTATING_KEYWORDS,
    AgentLoop,
    _apply_exclusion_filters,
    _compress_resource,
    _reject_if_mutating,
)
from core.config import ScanSettings

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


def _make_tool_use_response(
    tool_name: str, tool_id: str, arguments: dict
) -> AIResponse:
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
            _make_tool_use_response(
                "list_resources", "toolu_1", {"ignore_regions": []}
            ),
            _make_submit_response([finding_data], summary),
        ]

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        findings, exec_summary = loop.run(
            cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS
        )

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
                "cloud": "aws",
                "region": "us-east-1",
                "estimated_monthly_cost": 5.0,
                "waste_reason": "unattached",
                "recommendation": "delete",
                "priority": "low",
                "metrics_summary": {},
                "tags": {},
            },
            {
                "resource_id": "expensive-001",
                "resource_type": "AWS::EC2::NatGateway",
                "cloud": "aws",
                "region": "us-east-1",
                "estimated_monthly_cost": 94.0,
                "waste_reason": "no traffic",
                "recommendation": "delete",
                "priority": "high",
                "metrics_summary": {},
                "tags": {},
            },
        ]

        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.return_value = _make_submit_response(raw, "Two findings.")

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        findings, _ = loop.run(
            cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS
        )

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
            _make_tool_use_response(
                "list_resources", "toolu_1", {"ignore_regions": []}
            ),
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
                "get_cost",
                "toolu_2",
                {"resource_ids": ["nat-0abc123", "alb-xyz"], "days": 30},
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
        fake_ai.chat.return_value = _make_submit_response(
            [], "No idle resources found."
        )

        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=FakeCloudAdapter())
        findings, summary = loop.run(
            cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS
        )

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
        findings, summary = loop.run(
            cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS
        )

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
        findings, _ = loop.run(
            cloud="aws", ignore_regions=IGNORE_REGIONS, accounts=ACCOUNTS
        )
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

        assert fake_ai.chat.call_count == ScanSettings().max_iterations


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


# ------------------------------------------------------------------
# Exclusion filter tests
# ------------------------------------------------------------------


def _make_resources() -> list[Resource]:
    return [
        Resource(
            resource_id="r1",
            resource_type="AWS::EC2::Instance",
            cloud="aws",
            region="us-east-1",
            tags={"env": "prod"},
        ),
        Resource(
            resource_id="r2",
            resource_type="AWS::Lambda::Function",
            cloud="aws",
            region="us-east-1",
            tags={"cost-optimization": "excluded"},
        ),
        Resource(
            resource_id="r3",
            resource_type="AWS::RDS::DBInstance",
            cloud="aws",
            region="us-west-2",
            tags={"env": "dev"},
        ),
    ]


class TestExclusionFilters:
    def test_no_filters_returns_all(self, monkeypatch):
        monkeypatch.delenv("EXCLUDE_TAGS", raising=False)
        monkeypatch.delenv("EXCLUDE_RESOURCE_TYPES", raising=False)
        result = _apply_exclusion_filters(_make_resources())
        assert len(result) == 3

    def test_exclude_by_tag(self, monkeypatch):
        monkeypatch.setenv("EXCLUDE_TAGS", '{"cost-optimization": "excluded"}')
        monkeypatch.delenv("EXCLUDE_RESOURCE_TYPES", raising=False)
        result = _apply_exclusion_filters(_make_resources())
        assert len(result) == 2
        assert all(r.resource_id != "r2" for r in result)

    def test_exclude_by_resource_type(self, monkeypatch):
        monkeypatch.delenv("EXCLUDE_TAGS", raising=False)
        monkeypatch.setenv("EXCLUDE_RESOURCE_TYPES", "AWS::Lambda::Function")
        result = _apply_exclusion_filters(_make_resources())
        assert len(result) == 2
        assert all(r.resource_type != "AWS::Lambda::Function" for r in result)

    def test_exclude_multiple_types(self, monkeypatch):
        monkeypatch.delenv("EXCLUDE_TAGS", raising=False)
        monkeypatch.setenv(
            "EXCLUDE_RESOURCE_TYPES", "AWS::Lambda::Function,AWS::RDS::DBInstance"
        )
        result = _apply_exclusion_filters(_make_resources())
        assert len(result) == 1
        assert result[0].resource_id == "r1"

    def test_exclude_tags_and_types_combined(self, monkeypatch):
        monkeypatch.setenv("EXCLUDE_TAGS", '{"env": "dev"}')
        monkeypatch.setenv("EXCLUDE_RESOURCE_TYPES", "AWS::Lambda::Function")
        result = _apply_exclusion_filters(_make_resources())
        assert len(result) == 1
        assert result[0].resource_id == "r1"

    def test_invalid_json_in_exclude_tags_is_ignored(self, monkeypatch):
        monkeypatch.setenv("EXCLUDE_TAGS", "not-json")
        monkeypatch.delenv("EXCLUDE_RESOURCE_TYPES", raising=False)
        result = _apply_exclusion_filters(_make_resources())
        assert len(result) == 3


class TestParallelExecution:
    def _make_loop(self):
        fake_ai = MagicMock(spec=AIProvider)
        adapter = FakeCloudAdapter()
        loop = AgentLoop(ai_provider=fake_ai, cloud_adapter=adapter)
        loop._prefiltered_payload = []
        return loop

    def test_parallel_tools_execute_concurrently(self):
        loop = self._make_loop()
        import time

        call_times: list[float] = []
        original_execute = loop._execute

        def tracking_execute(tc):
            time.sleep(0.05)  # simulate work so threads overlap
            call_times.append(time.monotonic())
            return original_execute(tc)

        loop._execute = tracking_execute

        tool_calls = [
            ToolCall(
                id=f"tc_{i}",
                name="get_metrics",
                arguments={
                    "resource_id": f"r-{i}",
                    "resource_type": "AWS::EC2::Instance",
                },
            )
            for i in range(5)
        ]

        start = time.monotonic()
        results = loop._execute_tool_calls(tool_calls)
        elapsed = time.monotonic() - start

        assert len(results) == 5
        assert all(not r.is_error for r in results)
        # If truly parallel, 5×50ms tasks should complete well under 5×50ms=250ms
        assert elapsed < 0.20, f"Expected parallel execution, took {elapsed:.2f}s"

    def test_sequential_tools_stay_sequential(self):
        loop = self._make_loop()
        tool_calls = [
            ToolCall(
                id="tc_list",
                name="list_resources",
                arguments={"ignore_regions": []},
            ),
        ]
        results = loop._execute_tool_calls(tool_calls)
        assert len(results) == 1
        assert not results[0].is_error

    def test_mixed_parallel_and_sequential_preserves_order(self):
        loop = self._make_loop()
        tool_calls = [
            ToolCall(
                id="tc_1",
                name="get_metrics",
                arguments={
                    "resource_id": "r-1",
                    "resource_type": "AWS::EC2::Instance",
                },
            ),
            ToolCall(
                id="tc_2",
                name="list_resources",
                arguments={"ignore_regions": []},
            ),
            ToolCall(
                id="tc_3",
                name="get_last_activity",
                arguments={
                    "resource_id": "r-1",
                    "resource_type": "AWS::EC2::Instance",
                },
            ),
        ]
        results = loop._execute_tool_calls(tool_calls)
        assert [r.tool_call_id for r in results] == ["tc_1", "tc_2", "tc_3"]

    def test_adapter_concurrency_env_var(self, monkeypatch):
        monkeypatch.setenv("ADAPTER_CONCURRENCY", "5")
        from core.config import ScanSettings, clear_settings_cache

        clear_settings_cache()
        cfg = ScanSettings()
        assert cfg.adapter_concurrency == 5
        clear_settings_cache()


# ------------------------------------------------------------------
# Read-only guardrail tests
# ------------------------------------------------------------------


class TestReadOnlyGuardrail:
    """Verify that the agent loop blocks any mutating tool call."""

    def test_allowed_tools_pass(self):
        for tool in _ALLOWED_TOOLS:
            assert _reject_if_mutating(tool) is None

    @pytest.mark.parametrize(
        "tool_name",
        [
            "delete_resource",
            "terminate_instance",
            "stop_instance",
            "modify_db_instance",
            "create_snapshot",
            "remove_tags",
            "update_security_group",
            "resize_instance",
            "scale_cluster",
            "destroy_stack",
            "launch_instance",
            "restart_service",
            "execute_command",
            "run_command_on_host",
        ],
    )
    def test_mutating_tools_blocked(self, tool_name):
        result = _reject_if_mutating(tool_name)
        assert result is not None
        assert "BLOCKED" in result
        assert "read-only" in result

    def test_unknown_tool_blocked(self):
        result = _reject_if_mutating("some_random_tool")
        assert result is not None
        assert "BLOCKED" in result
        assert "Unknown tool" in result

    def test_case_insensitive_blocking(self):
        assert _reject_if_mutating("Delete_Resource") is not None
        assert _reject_if_mutating("TERMINATE_INSTANCE") is not None

    def test_blocklist_covers_common_cloud_operations(self):
        dangerous_ops = [
            "ec2_delete_instance",
            "rds_stop_cluster",
            "s3_remove_bucket",
            "lambda_update_function",
            "ecs_scale_service",
            "eks_create_nodegroup",
        ]
        for op in dangerous_ops:
            result = _reject_if_mutating(op)
            assert result is not None, f"{op} should be blocked"

    def test_adapter_interface_is_read_only(self):
        """CloudAdapter subclasses must not define methods with mutating names."""

        from adapters.base import CloudAdapter

        for subclass in CloudAdapter.__subclasses__():
            methods = [
                m
                for m in dir(subclass)
                if not m.startswith("_") and callable(getattr(subclass, m))
            ]
            for method in methods:
                name_lower = method.lower()
                for keyword in _MUTATING_KEYWORDS:
                    assert keyword not in name_lower, (
                        f"Adapter {subclass.__name__}.{method}() contains "
                        f"mutating keyword '{keyword}'. "
                        f"CloudAdapter implementations must be read-only."
                    )
