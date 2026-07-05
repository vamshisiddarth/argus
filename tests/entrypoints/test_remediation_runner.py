"""Tests for the shared remediation runner (entrypoints/_remediation.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.models.finding import ResourceFinding


def _finding(**kwargs) -> ResourceFinding:
    defaults = dict(
        resource_id="i-abc",
        resource_type="AWS::EC2::Instance",
        cloud="aws",
        region="us-east-1",
        name="idle",
        estimated_monthly_cost=200.0,
        waste_reason="CPU < 2%",
        recommendation="Stop",
        priority="high",
        metrics_summary={},
        tags={},
        last_activity=None,
        scan_time=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return ResourceFinding(**defaults)


def _write_policy(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "ec2-stop.yaml").write_text(
        "version: '1'\n"
        "policy_id: ec2-stop\n"
        "name: Stop idle EC2\n"
        "resource_type: AWS::EC2::Instance\n"
        "action: stop\n"
        "conditions:\n"
        "  min_estimated_monthly_cost_usd: 100\n"
    )


class TestRunRemediationNoDir:
    def test_returns_empty_when_policy_dir_missing(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation

        monkeypatch.setenv("ARGUS_POLICY_DIR", str(tmp_path / "nonexistent"))
        result = run_remediation([_finding()])
        assert result == []


class TestRunRemediationNoPolicies:
    def test_returns_empty_when_dir_empty(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation

        tmp_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("ARGUS_POLICY_DIR", str(tmp_path))
        result = run_remediation([_finding()])
        assert result == []


class TestRunRemediationNoMatch:
    def test_returns_empty_when_no_findings_match(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation

        _write_policy(tmp_path)
        monkeypatch.setenv("ARGUS_POLICY_DIR", str(tmp_path))
        result = run_remediation([_finding(estimated_monthly_cost=10.0)])
        assert result == []


class TestRunRemediationJiraNotConfigured:
    def test_returns_empty_when_jira_env_missing(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation

        _write_policy(tmp_path)
        monkeypatch.setenv("ARGUS_POLICY_DIR", str(tmp_path))
        monkeypatch.delenv("JIRA_BASE_URL", raising=False)
        monkeypatch.delenv("JIRA_USER_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        result = run_remediation([_finding()])
        assert result == []


class TestRunRemediationSuccess:
    def _setup(self, tmp_path, monkeypatch):
        policy_dir = tmp_path / "policies"
        _write_policy(policy_dir)
        cfg = tmp_path / "integrations.yaml"
        cfg.write_text("version: '1'\njira:\n  project: INFRA\n")
        monkeypatch.setenv("ARGUS_POLICY_DIR", str(policy_dir))
        monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
        monkeypatch.setenv("JIRA_USER_EMAIL", "bot@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        monkeypatch.setenv("ARGUS_INTEGRATIONS_CONFIG", str(cfg))

    def test_returns_ticket_urls(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation

        self._setup(tmp_path, monkeypatch)
        mock_tracker = MagicMock()
        mock_tracker.create.return_value = "https://jira.example.com/browse/INFRA-1"
        with patch(
            "integrations.jira.tracker.JiraTracker.from_env",
            return_value=mock_tracker,
        ):
            result = run_remediation([_finding()])
        assert result == ["https://jira.example.com/browse/INFRA-1"]

    def test_ticket_failure_is_isolated(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation

        self._setup(tmp_path, monkeypatch)
        mock_tracker = MagicMock()
        mock_tracker.create.side_effect = Exception("Jira down")
        with patch(
            "integrations.jira.tracker.JiraTracker.from_env",
            return_value=mock_tracker,
        ):
            result = run_remediation([_finding()])
        assert result == []
