from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from core.models.finding import ResourceFinding
from core.remediation.models import ChangeProposal, Condition, Policy
from integrations.base import TrackerError
from integrations.jira.formatter import fingerprint
from integrations.jira.tracker import JiraTracker, _dedup_label

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _finding(**kwargs) -> ResourceFinding:
    defaults = dict(
        resource_id="i-abc123",
        resource_type="AWS::EC2::Instance",
        cloud="aws",
        region="us-east-1",
        name="idle-vm",
        estimated_monthly_cost=120.0,
        waste_reason="CPU < 2% for 30 days",
        recommendation="Stop or terminate",
        priority="high",
        metrics_summary={},
        tags={},
        last_activity=None,
        scan_time=datetime(2026, 7, 4, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return ResourceFinding(**defaults)


def _policy(**kwargs) -> Policy:
    defaults = dict(
        policy_id="ec2-stop",
        name="Stop idle EC2",
        resource_type="AWS::EC2::Instance",
        conditions=Condition(min_estimated_monthly_cost_usd=50.0),
        action="stop",
        weight=5,
        source_file="config/policies/ec2.yaml",
    )
    defaults.update(kwargs)
    return Policy(**defaults)


def _proposal(**kwargs) -> ChangeProposal:
    defaults = dict(
        finding=_finding(),
        policy=_policy(),
        runbook="aws ec2 stop-instances --instance-ids i-abc123",
        estimated_monthly_cost_usd=120.0,
    )
    defaults.update(kwargs)
    return ChangeProposal(**defaults)


def _make_tracker(client: MagicMock) -> JiraTracker:
    return JiraTracker(
        client,
        project="INFRA",
        issue_type="Task",
        default_labels=["argus"],
        priority_map={"high": "High", "medium": "Medium", "low": "Low"},
    )


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.issue_url.side_effect = lambda key: f"https://jira.example.com/browse/{key}"
    return client


# ---------------------------------------------------------------------------
# _dedup_label
# ---------------------------------------------------------------------------


class TestDedupLabel:
    def test_format(self):
        assert _dedup_label(_proposal()) == "argus:i-abc123:ec2-stop"

    def test_spaces_replaced(self):
        p = _proposal(finding=_finding(resource_id="my resource"))
        assert " " not in _dedup_label(p)

    def test_quotes_stripped(self):
        p = _proposal(finding=_finding(resource_id='id"with"quotes'))
        assert '"' not in _dedup_label(p)


# ---------------------------------------------------------------------------
# create — no existing ticket → create new
# ---------------------------------------------------------------------------


class TestCreateNew:
    def test_returns_new_ticket_url(self):
        client = _mock_client()
        client.search.return_value = []
        client.create_issue.return_value = {"key": "INFRA-1", "id": "100"}
        tracker = _make_tracker(client)

        url = tracker.create(_proposal())
        assert url == "https://jira.example.com/browse/INFRA-1"

    def test_calls_create_issue(self):
        client = _mock_client()
        client.search.return_value = []
        client.create_issue.return_value = {"key": "INFRA-1", "id": "100"}
        tracker = _make_tracker(client)

        tracker.create(_proposal())
        client.create_issue.assert_called_once()

    def test_dedup_label_in_jql(self):
        client = _mock_client()
        client.search.return_value = []
        client.create_issue.return_value = {"key": "INFRA-1", "id": "100"}
        tracker = _make_tracker(client)

        tracker.create(_proposal())
        jql = client.search.call_args[0][0]
        assert "argus:i-abc123:ec2-stop" in jql

    def test_raises_tracker_error_on_create_failure(self):
        client = _mock_client()
        client.search.return_value = []
        client.create_issue.side_effect = Exception("API error")
        tracker = _make_tracker(client)

        with pytest.raises(TrackerError, match="create_issue failed"):
            tracker.create(_proposal())

    def test_raises_tracker_error_on_search_failure(self):
        client = _mock_client()
        client.search.side_effect = Exception("network error")
        tracker = _make_tracker(client)

        with pytest.raises(TrackerError, match="search failed"):
            tracker.create(_proposal())


# ---------------------------------------------------------------------------
# create — existing open ticket, analysis unchanged → silent skip
# ---------------------------------------------------------------------------


def _issue_with_snapshot(key: str, proposal: ChangeProposal) -> dict:
    fp = fingerprint(proposal)
    text = f"Some description\n<!-- argus-snapshot: {json.dumps(fp)} -->"
    return {
        "key": key,
        "fields": {
            "description": text,
            "status": {"statusCategory": {"key": "indeterminate"}},
        },
    }


class TestExistingTicketUnchanged:
    def test_returns_existing_url(self):
        p = _proposal()
        client = _mock_client()
        client.search.return_value = [_issue_with_snapshot("INFRA-5", p)]
        tracker = _make_tracker(client)

        url = tracker.create(p)
        assert url == "https://jira.example.com/browse/INFRA-5"

    def test_does_not_create_new_issue(self):
        p = _proposal()
        client = _mock_client()
        client.search.return_value = [_issue_with_snapshot("INFRA-5", p)]
        tracker = _make_tracker(client)

        tracker.create(p)
        client.create_issue.assert_not_called()

    def test_does_not_add_comment_when_unchanged(self):
        p = _proposal()
        client = _mock_client()
        client.search.return_value = [_issue_with_snapshot("INFRA-5", p)]
        tracker = _make_tracker(client)

        tracker.create(p)
        client.add_comment.assert_not_called()


# ---------------------------------------------------------------------------
# create — existing open ticket, analysis changed → add comment
# ---------------------------------------------------------------------------


def _issue_stale(key: str) -> dict:
    old_fp = {"cost": 50.0, "priority": "low", "reason_hash": "000000"}
    text = f"Some description\n<!-- argus-snapshot: {json.dumps(old_fp)} -->"
    return {
        "key": key,
        "fields": {
            "description": text,
            "status": {"statusCategory": {"key": "indeterminate"}},
        },
    }


class TestExistingTicketChanged:
    def test_adds_comment(self):
        client = _mock_client()
        client.search.return_value = [_issue_stale("INFRA-7")]
        tracker = _make_tracker(client)

        tracker.create(_proposal())
        assert client.add_comment.call_count == 1
        key_arg, comment_arg = client.add_comment.call_args[0]
        assert key_arg == "INFRA-7"
        # comment is now an ADF dict
        assert isinstance(comment_arg, dict) and comment_arg.get("type") == "paragraph"

    def test_returns_existing_url(self):
        client = _mock_client()
        client.search.return_value = [_issue_stale("INFRA-7")]
        tracker = _make_tracker(client)

        url = tracker.create(_proposal())
        assert "INFRA-7" in url

    def test_does_not_create_new_issue(self):
        client = _mock_client()
        client.search.return_value = [_issue_stale("INFRA-7")]
        tracker = _make_tracker(client)

        tracker.create(_proposal())
        client.create_issue.assert_not_called()


# ---------------------------------------------------------------------------
# create — existing ticket but no snapshot → add comment (treat as changed)
# ---------------------------------------------------------------------------


class TestExistingTicketNoSnapshot:
    def test_adds_comment_when_snapshot_missing(self):
        client = _mock_client()
        client.search.return_value = [
            {
                "key": "INFRA-3",
                "fields": {
                    "description": "No snapshot here",
                    "status": {"statusCategory": {"key": "indeterminate"}},
                },
            }
        ]
        tracker = _make_tracker(client)
        tracker.create(_proposal())
        client.add_comment.assert_called_once()


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------


class TestFromEnv:
    def test_raises_if_env_vars_missing(self, monkeypatch):
        monkeypatch.delenv("JIRA_BASE_URL", raising=False)
        monkeypatch.delenv("JIRA_USER_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        with pytest.raises(TrackerError, match="Missing required env vars"):
            JiraTracker.from_env()

    def test_raises_if_project_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
        monkeypatch.setenv("JIRA_USER_EMAIL", "bot@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        cfg = tmp_path / "integrations.yaml"
        cfg.write_text("version: '1'\njira:\n  issue_type: Task\n")
        monkeypatch.setenv("ARGUS_INTEGRATIONS_CONFIG", str(cfg))
        with pytest.raises(TrackerError, match="missing 'jira.project'"):
            JiraTracker.from_env()

    def test_builds_tracker_with_valid_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
        monkeypatch.setenv("JIRA_USER_EMAIL", "bot@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        cfg = tmp_path / "integrations.yaml"
        cfg.write_text("version: '1'\njira:\n  project: INFRA\n")
        monkeypatch.setenv("ARGUS_INTEGRATIONS_CONFIG", str(cfg))
        tracker = JiraTracker.from_env()
        assert isinstance(tracker, JiraTracker)
        assert tracker._project == "INFRA"

    def test_missing_config_file_uses_defaults(self, monkeypatch):
        monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
        monkeypatch.setenv("JIRA_USER_EMAIL", "bot@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        monkeypatch.setenv("ARGUS_INTEGRATIONS_CONFIG", "/nonexistent/path.yaml")
        # Missing project should raise even with missing config file
        with pytest.raises(TrackerError, match="missing 'jira.project'"):
            JiraTracker.from_env()

    def test_bad_yaml_in_config_falls_back_to_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
        monkeypatch.setenv("JIRA_USER_EMAIL", "bot@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        cfg = tmp_path / "integrations.yaml"
        cfg.write_text("key: [unclosed")
        monkeypatch.setenv("ARGUS_INTEGRATIONS_CONFIG", str(cfg))
        # Bad YAML → config load fails → no project → raises TrackerError
        with pytest.raises(TrackerError):
            JiraTracker.from_env()


class TestClose:
    def test_close_logs_and_does_not_raise(self, caplog):
        import logging
        client = _mock_client()
        tracker = _make_tracker(client)
        with caplog.at_level(logging.INFO):
            tracker.close("https://jira.example.com/browse/INFRA-5", "resource deleted")
        assert "INFRA-5" in caplog.text


class TestExtractDescriptionText:
    def test_adf_dict_extracts_text(self):
        from integrations.jira.tracker import _extract_description_text
        issue = {
            "fields": {
                "description": {
                    "version": 1,
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Hello world"}],
                        }
                    ],
                }
            }
        }
        result = _extract_description_text(issue)
        assert "Hello world" in result

    def test_string_description_returned_as_is(self):
        from integrations.jira.tracker import _extract_description_text
        issue = {"fields": {"description": "plain text"}}
        assert _extract_description_text(issue) == "plain text"

    def test_missing_description_returns_empty(self):
        from integrations.jira.tracker import _extract_description_text
        assert _extract_description_text({"fields": {}}) == ""


class TestCommentFailureSilent:
    def test_comment_failure_logged_not_raised(self):
        client = _mock_client()
        client.search.return_value = [
            {"key": "INFRA-7", "fields": {
                "description": "", "status": {"name": "Open"}
            }}
        ]
        client.add_comment.side_effect = Exception("network error")
        tracker = _make_tracker(client)
        # Should not raise — failure is logged as warning
        url = tracker.create(_proposal())
        assert "INFRA-7" in url
