"""
End-to-end CLI smoke test.

Exercises the full path: CLI → entrypoint → AgentLoop → report generation
with a mock adapter and mock AI provider. No cloud credentials needed.
Proves the wiring works — if this test passes, `argus --cloud aws --run-now`
will reach the report stage without import errors or plumbing bugs.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from adapters.base import MetricSummary, Resource
from ai.base import AIResponse, ToolCall


def _make_resources() -> list[Resource]:
    return [
        Resource(
            resource_id="i-0abc123",
            resource_type="AWS::EC2::Instance",
            cloud="aws",
            region="us-east-1",
            name="idle-web-01",
            tags={"Env": "dev"},
        ),
        Resource(
            resource_id="i-0def456",
            resource_type="AWS::EC2::Instance",
            cloud="aws",
            region="us-east-1",
            name="idle-web-02",
            tags={},
        ),
    ]


def _make_mock_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.list_resources.return_value = _make_resources()
    adapter.get_cost.return_value = {"i-0abc123": 45.0, "i-0def456": 12.0}
    adapter.get_metrics.return_value = MetricSummary(
        resource_id="i-0abc123",
        resource_type="AWS::EC2::Instance",
        period_days=14,
        metrics={"CPUUtilization": {"avg": 0.5, "max": 1.2}},
    )
    adapter.get_last_activity.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return adapter


def _make_mock_ai() -> MagicMock:
    """AI that calls list_resources, then immediately submits findings."""
    ai = MagicMock()

    # First call: AI asks to list resources
    list_response = AIResponse(
        stop_reason="tool_use",
        text="Let me list all resources.",
        tool_calls=[
            ToolCall(
                id="tc_1",
                name="list_resources",
                arguments={"ignore_regions": []},
            )
        ],
        input_tokens=500,
        output_tokens=200,
    )

    # Second call: AI submits findings
    submit_response = AIResponse(
        stop_reason="tool_use",
        text="Analysis complete.",
        tool_calls=[
            ToolCall(
                id="tc_2",
                name="submit_findings",
                arguments={
                    "findings": [
                        {
                            "resource_id": "i-0abc123",
                            "resource_type": "EC2",
                            "region": "us-east-1",
                            "name": "idle-web-01",
                            "estimated_monthly_cost": 45.0,
                            "waste_reason": "CPU < 1% for 90 days",
                            "recommendation": "Terminate or downsize",
                            "priority": "high",
                            "metrics_summary": {"cpu_avg": 0.5},
                            "tags": {"Env": "dev"},
                        }
                    ],
                    "executive_summary": "Found 1 idle EC2 instance costing $45/mo.",
                },
            )
        ],
        input_tokens=1000,
        output_tokens=500,
    )

    ai.chat.side_effect = [list_response, submit_response]
    return ai


class TestCLISmokeAWS:
    """Full CLI → report path for AWS with mocked adapter + AI."""

    def test_dry_run_produces_report(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_BUDGET_USD", "10.0")

        mock_adapter = _make_mock_adapter()
        mock_ai = _make_mock_ai()

        with (
            patch(
                "adapters.aws.adapter.AWSAdapter.for_account",
                return_value=mock_adapter,
            ),
            patch("ai.anthropic.AnthropicProvider", return_value=mock_ai),
            patch(
                "entrypoints.aws_lambda._get_current_account_id",
                return_value="123456789012",
            ),
        ):
            from entrypoints.cli import main

            main(["--cloud", "aws", "--run-now", "--dry-run"])

        # Verify local report was saved
        report_files = list(tmp_path.rglob("*.json"))
        assert len(report_files) >= 1

        report = json.loads(report_files[0].read_text())
        assert report["cloud"] == "aws"
        assert report["findings_count"] == 1
        assert report["total_estimated_waste_usd"] == 45.0
        assert report["agent_input_tokens"] == 1500
        assert report["agent_output_tokens"] == 700
        assert report["estimated_agent_cost_usd"] > 0
        assert report["accounts_scanned"] == ["123456789012"]


class TestCLISmokeGCP:
    """Full CLI → report path for GCP with mocked adapter + AI."""

    def test_dry_run_produces_report(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_BUDGET_USD", "10.0")

        mock_adapter = _make_mock_adapter()
        mock_ai = _make_mock_ai()

        with (
            patch(
                "adapters.gcp.adapter.GCPAdapter.from_env",
                return_value=mock_adapter,
            ),
            patch("ai.anthropic.AnthropicProvider", return_value=mock_ai),
        ):
            from entrypoints.cli import main

            main(["--cloud", "gcp", "--run-now", "--dry-run"])

        report_files = list(tmp_path.rglob("*.json"))
        assert len(report_files) >= 1

        report = json.loads(report_files[0].read_text())
        assert report["cloud"] == "gcp"
        assert report["findings_count"] == 1
        assert report["agent_input_tokens"] == 1500


class TestCLISmokeAzure:
    """Full CLI → report path for Azure with mocked adapter + AI."""

    def test_dry_run_produces_report(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-123")
        monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_BUDGET_USD", "10.0")

        mock_adapter = _make_mock_adapter()
        mock_ai = _make_mock_ai()

        with (
            patch(
                "adapters.azure.adapter.AzureAdapter.from_env",
                return_value=mock_adapter,
            ),
            patch("ai.anthropic.AnthropicProvider", return_value=mock_ai),
        ):
            from entrypoints.cli import main

            main(["--cloud", "azure", "--run-now", "--dry-run"])

        report_files = list(tmp_path.rglob("*.json"))
        assert len(report_files) >= 1

        report = json.loads(report_files[0].read_text())
        assert report["cloud"] == "azure"
        assert report["findings_count"] == 1


class TestCLISmokeBudgetExceeded:
    """Verify the budget enforcement works end-to-end."""

    def test_budget_exceeded_aborts_gracefully(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_BUDGET_USD", "0.0001")

        mock_adapter = _make_mock_adapter()

        # AI returns huge token counts to blow the budget
        ai = MagicMock()
        ai.chat.return_value = AIResponse(
            stop_reason="tool_use",
            text="Analyzing...",
            tool_calls=[
                ToolCall(
                    id="tc_1",
                    name="list_resources",
                    arguments={"ignore_regions": []},
                )
            ],
            input_tokens=1_000_000,
            output_tokens=500_000,
        )

        with (
            patch(
                "adapters.aws.adapter.AWSAdapter.for_account",
                return_value=mock_adapter,
            ),
            patch("ai.anthropic.AnthropicProvider", return_value=ai),
            patch(
                "entrypoints.aws_lambda._get_current_account_id",
                return_value="123456789012",
            ),
            patch("core.reports.delivery.notify_all"),
        ):
            from entrypoints.cli import main

            main(["--cloud", "aws", "--run-now", "--dry-run"])

        # Should still produce a report (with 0 findings and budget message)
        report_files = list(tmp_path.rglob("*.json"))
        assert len(report_files) >= 1

        report = json.loads(report_files[0].read_text())
        assert report["findings_count"] == 0
        assert "budget" in report["executive_summary"].lower()
