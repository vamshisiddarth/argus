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
    def teardown_method(self):
        from core.config import clear_settings_cache

        clear_settings_cache()

    def _setup(self, tmp_path, monkeypatch):
        from core.config import clear_settings_cache

        # conftest forces DRY_RUN=true for entrypoint tests; these exercise
        # the live Jira path, so turn it off explicitly.
        monkeypatch.setenv("DRY_RUN", "false")
        clear_settings_cache()
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


class TestRunRemediationDryRun:
    """DRY_RUN must never reach Jira, even with credentials configured."""

    def teardown_method(self):
        from core.config import clear_settings_cache

        clear_settings_cache()

    def _setup(self, tmp_path, monkeypatch):
        from core.config import clear_settings_cache

        TestRunRemediationSuccess()._setup(tmp_path, monkeypatch)
        monkeypatch.setenv("DRY_RUN", "true")
        clear_settings_cache()

    def test_no_tracker_built_and_no_urls(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation

        self._setup(tmp_path, monkeypatch)
        with patch("integrations.jira.tracker.JiraTracker.from_env") as from_env:
            result = run_remediation([_finding()])
        assert result == []
        from_env.assert_not_called()

    def test_logs_would_track_per_proposal(self, tmp_path, monkeypatch, caplog):
        from entrypoints._remediation import run_remediation

        self._setup(tmp_path, monkeypatch)
        with caplog.at_level("INFO", logger="entrypoints._remediation"):
            run_remediation([_finding(resource_id="i-1"), _finding(resource_id="i-2")])
        would = [m for m in caplog.messages if m.startswith("remediation_would_track")]
        assert len(would) == 2
        assert any("resource_id=i-1" in m and "policy_id=ec2-stop" in m for m in would)
        assert any(
            "remediation_summary" in m and "proposals=2" in m and "dry_run=True" in m
            for m in caplog.messages
        )


class TestRunRemediationPartialFailure:
    def teardown_method(self):
        from core.config import clear_settings_cache

        clear_settings_cache()

    def test_one_failure_does_not_stop_the_rest(self, tmp_path, monkeypatch, caplog):
        from entrypoints._remediation import run_remediation
        from integrations.base import TrackerError

        TestRunRemediationSuccess()._setup(tmp_path, monkeypatch)
        mock_tracker = MagicMock()
        mock_tracker.create.side_effect = [
            "https://jira.example.com/browse/INFRA-1",
            "https://jira.example.com/browse/INFRA-2",
            TrackerError("Jira create_issue failed: 429 Too Many Requests"),
            "https://jira.example.com/browse/INFRA-4",
            "https://jira.example.com/browse/INFRA-5",
        ]
        findings = [_finding(resource_id=f"i-{n}") for n in range(1, 6)]
        with (
            patch(
                "integrations.jira.tracker.JiraTracker.from_env",
                return_value=mock_tracker,
            ),
            caplog.at_level("INFO", logger="entrypoints._remediation"),
        ):
            result = run_remediation(findings)

        assert len(result) == 4
        assert mock_tracker.create.call_count == 5
        failed = [m for m in caplog.messages if "remediation_ticket_failed" in m]
        assert len(failed) == 1 and "429" in failed[0]
        assert any(
            "remediation_summary" in m and "tracked=4" in m and "failed=1" in m
            for m in caplog.messages
        )

    def test_tracker_init_failure_returns_empty(self, tmp_path, monkeypatch):
        from entrypoints._remediation import run_remediation
        from integrations.base import TrackerError

        TestRunRemediationSuccess()._setup(tmp_path, monkeypatch)
        with patch(
            "integrations.jira.tracker.JiraTracker.from_env",
            side_effect=TrackerError("401 Unauthorized"),
        ):
            assert run_remediation([_finding()]) == []


class TestRunRemediationAbortLogging:
    """Operators must be able to tell a Jira problem from a bug."""

    def teardown_method(self):
        from core.config import clear_settings_cache

        clear_settings_cache()

    def test_tracker_error_logged_with_type_no_traceback(
        self, tmp_path, monkeypatch, caplog
    ):
        from entrypoints._remediation import run_remediation
        from integrations.base import TrackerError

        TestRunRemediationSuccess()._setup(tmp_path, monkeypatch)
        with (
            patch(
                "integrations.jira.tracker.JiraTracker.from_env",
                side_effect=TrackerError("401 Unauthorized"),
            ),
            caplog.at_level("WARNING", logger="entrypoints._remediation"),
        ):
            run_remediation([_finding()])
        [rec] = [r for r in caplog.records if "remediation_aborted" in r.message]
        assert "error_type=TrackerError" in rec.message
        assert rec.exc_info is None

    def test_unexpected_error_logged_with_traceback(
        self, tmp_path, monkeypatch, caplog
    ):
        from entrypoints._remediation import run_remediation

        TestRunRemediationSuccess()._setup(tmp_path, monkeypatch)
        with (
            patch("core.remediation.engine.evaluate", side_effect=KeyError("priority")),
            caplog.at_level("WARNING", logger="entrypoints._remediation"),
        ):
            assert run_remediation([_finding()]) == []
        [rec] = [r for r in caplog.records if "remediation_aborted" in r.message]
        assert "error_type=KeyError" in rec.message
        assert rec.exc_info is not None

    def test_ticket_failure_includes_error_type(self, tmp_path, monkeypatch, caplog):
        from entrypoints._remediation import run_remediation

        TestRunRemediationSuccess()._setup(tmp_path, monkeypatch)
        mock_tracker = MagicMock()
        mock_tracker.create.side_effect = ConnectionError("reset")
        with (
            patch(
                "integrations.jira.tracker.JiraTracker.from_env",
                return_value=mock_tracker,
            ),
            caplog.at_level("WARNING", logger="entrypoints._remediation"),
        ):
            run_remediation([_finding()])
        assert any(
            "remediation_ticket_failed" in m and "error_type=ConnectionError" in m
            for m in caplog.messages
        )
