from __future__ import annotations

import json
from datetime import datetime, timezone

from core.models.finding import ResourceFinding
from core.remediation.models import ChangeProposal, Condition, Policy
from integrations.jira.formatter import (
    build_issue_fields,
    build_update_comment,
    extract_snapshot,
    fingerprint,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _finding(**kwargs) -> ResourceFinding:
    defaults = dict(
        resource_id="db-idle-01",
        resource_type="AWS::RDS::DBInstance",
        cloud="aws",
        region="eu-west-1",
        name="idle-db",
        estimated_monthly_cost=340.0,
        waste_reason="CPU averaged 4% over 14 days, zero connections",
        recommendation="Resize to db.t3.small",
        priority="high",
        metrics_summary={"CPUUtilization": 4.2, "DatabaseConnections": 0.0},
        tags={},
        last_activity=None,
        scan_time=datetime(2026, 7, 4, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return ResourceFinding(**defaults)


def _policy(**kwargs) -> Policy:
    defaults = dict(
        policy_id="rds-resize",
        name="Resize underutilized RDS",
        resource_type="AWS::RDS::DBInstance",
        conditions=Condition(min_estimated_monthly_cost_usd=100.0),
        action="resize",
        weight=10,
        source_file="config/policies/rds_resize.yaml",
    )
    defaults.update(kwargs)
    return Policy(**defaults)


def _proposal(**kwargs) -> ChangeProposal:
    defaults = dict(
        finding=_finding(),
        policy=_policy(),
        runbook="aws rds modify-db-instance --db-instance-identifier db-idle-01",
        estimated_monthly_cost_usd=340.0,
    )
    defaults.update(kwargs)
    return ChangeProposal(**defaults)


_JIRA_KWARGS = dict(
    project="INFRA",
    issue_type="Task",
    default_labels=["argus"],
    priority_map={"high": "High", "medium": "Medium", "low": "Low"},
    dedup_label="argus:db-idle-01:rds-resize",
)


def _adf_text(adf: dict) -> str:
    """Walk an ADF doc and collect all text node values."""
    parts: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []):
                _walk(child)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(adf)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# build_issue_fields
# ---------------------------------------------------------------------------


class TestBuildIssueFields:
    def test_summary_contains_resource_name(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "idle-db" in fields["summary"]

    def test_summary_contains_cost(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "340" in fields["summary"]

    def test_summary_contains_priority(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "high" in fields["summary"]

    def test_summary_contains_action_verb(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "Resize" in fields["summary"]

    def test_project_key_set(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert fields["project"]["key"] == "INFRA"

    def test_issue_type_set(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert fields["issuetype"]["name"] == "Task"

    def test_priority_mapped(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert fields["priority"]["name"] == "High"

    def test_priority_fallback_medium(self):
        p = _proposal(finding=_finding(priority="low"))
        fields = build_issue_fields(p, **_JIRA_KWARGS)
        assert fields["priority"]["name"] == "Low"

    def test_dedup_label_in_labels(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "argus:db-idle-01:rds-resize" in fields["labels"]

    def test_default_labels_included(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "argus" in fields["labels"]

    def test_priority_label_in_labels(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "argus-priority-high" in fields["labels"]

    def test_action_label_in_labels(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert "argus-action-resize" in fields["labels"]

    def test_description_is_adf(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert fields["description"]["type"] == "doc"
        assert fields["description"]["version"] == 1

    def test_description_contains_waste_reason(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        text = _adf_text(fields["description"])
        assert "CPU averaged" in text

    def test_description_contains_runbook(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        text = _adf_text(fields["description"])
        assert "modify-db-instance" in text

    def test_description_contains_human_approval_warning(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        text = _adf_text(fields["description"])
        assert "Human approval required" in text

    def test_description_contains_snapshot_marker(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        text = _adf_text(fields["description"])
        assert "argus-snapshot" in text

    def test_description_contains_metrics_table(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        # Finding has CPUUtilization and DatabaseConnections in metrics_summary
        text = _adf_text(fields["description"])
        assert "CPUUtilization" in text

    def test_report_url_included_when_given(self):
        fields = build_issue_fields(
            _proposal(), **_JIRA_KWARGS, report_url="https://example.com/report"
        )
        text = _adf_text(fields["description"])
        assert "https://example.com/report" in text

    def test_no_metrics_table_when_metrics_empty(self):
        p = _proposal(finding=_finding(metrics_summary={}))
        fields = build_issue_fields(p, **_JIRA_KWARGS)
        # No "Key Metrics" heading when metrics_summary is empty
        text = _adf_text(fields["description"])
        assert "Key Metrics" not in text

    def test_uses_resource_id_when_name_is_none(self):
        p = _proposal(finding=_finding(name=None))
        fields = build_issue_fields(p, **_JIRA_KWARGS)
        assert "db-idle-01" in fields["summary"]

    def test_description_contains_proposal_id(self):
        proposal = _proposal()
        fields = build_issue_fields(proposal, **_JIRA_KWARGS)
        text = _adf_text(fields["description"])
        assert proposal.proposal_id in text


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_returns_expected_keys(self):
        fp = fingerprint(_proposal())
        assert set(fp.keys()) == {"proposal_id", "cost", "priority", "reason_hash"}

    def test_cost_rounded(self):
        fp = fingerprint(_proposal())
        assert fp["cost"] == 340.0

    def test_priority_present(self):
        fp = fingerprint(_proposal())
        assert fp["priority"] == "high"

    def test_reason_hash_present(self):
        fp = fingerprint(_proposal())
        assert len(fp["reason_hash"]) == 8

    def test_proposal_id_present(self):
        proposal = _proposal()
        fp = fingerprint(proposal)
        assert fp["proposal_id"] == proposal.proposal_id

    def test_same_proposal_same_fingerprint(self):
        p = _proposal()
        assert fingerprint(p) == fingerprint(p)

    def test_different_cost_different_fingerprint(self):
        a = fingerprint(_proposal(estimated_monthly_cost_usd=100.0))
        b = fingerprint(_proposal(estimated_monthly_cost_usd=200.0))
        assert a["cost"] != b["cost"]

    def test_different_priority_different_fingerprint(self):
        a = fingerprint(_proposal(finding=_finding(priority="high")))
        b = fingerprint(_proposal(finding=_finding(priority="low")))
        assert a["priority"] != b["priority"]


# ---------------------------------------------------------------------------
# extract_snapshot
# ---------------------------------------------------------------------------


class TestExtractSnapshot:
    def test_extracts_valid_snapshot(self):
        snap = {"cost": 340.0, "priority": "high", "reason_hash": "abc123"}
        text = f"some text\n<!-- argus-snapshot: {json.dumps(snap)} -->"
        result = extract_snapshot(text)
        assert result == snap

    def test_returns_none_if_missing(self):
        assert extract_snapshot("no snapshot here") is None

    def test_returns_none_if_malformed_json(self):
        assert extract_snapshot("<!-- argus-snapshot: not-json -->") is None

    def test_roundtrip_from_build_fields(self):
        proposal = _proposal()
        fields = build_issue_fields(proposal, **_JIRA_KWARGS)
        text = _adf_text(fields["description"])
        extracted = extract_snapshot(text)
        assert extracted is not None
        assert extracted["priority"] == "high"
        assert extracted["proposal_id"] == proposal.proposal_id


# ---------------------------------------------------------------------------
# build_update_comment
# ---------------------------------------------------------------------------


class TestBuildUpdateComment:
    def test_returns_adf_dict(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "aaa"}
        comment = build_update_comment(_proposal(), stored)
        assert isinstance(comment, dict)
        assert comment["type"] == "paragraph"

    def test_includes_date_header(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "aaa"}
        comment = build_update_comment(_proposal(), stored)
        text = _adf_text(comment)
        assert "re-scan update" in text

    def test_shows_cost_change(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "aaa"}
        p = _proposal(estimated_monthly_cost_usd=280.0)
        comment = build_update_comment(p, stored)
        text = _adf_text(comment)
        assert "340" in text
        assert "280" in text

    def test_shows_priority_change(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "aaa"}
        p = _proposal(finding=_finding(priority="medium"))
        comment = build_update_comment(p, stored)
        text = _adf_text(comment)
        assert "high" in text
        assert "medium" in text

    def test_shows_reason_when_hash_changes(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "different"}
        comment = build_update_comment(_proposal(), stored)
        text = _adf_text(comment)
        assert "CPU averaged" in text

    def test_no_cost_line_when_unchanged(self):
        fp = fingerprint(_proposal())
        comment = build_update_comment(_proposal(), fp)
        text = _adf_text(comment)
        assert "Cost:" not in text
        assert "Priority:" not in text
