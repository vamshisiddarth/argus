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
        metrics_summary={},
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

    def test_description_is_adf(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        assert fields["description"]["type"] == "doc"

    def test_description_contains_waste_reason(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        desc_text = fields["description"]["content"][0]["content"][0]["text"]
        assert "CPU averaged" in desc_text

    def test_description_contains_runbook(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        desc_text = fields["description"]["content"][0]["content"][0]["text"]
        assert "modify-db-instance" in desc_text

    def test_description_contains_snapshot_marker(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        desc_text = fields["description"]["content"][0]["content"][0]["text"]
        assert "argus-snapshot" in desc_text

    def test_report_url_included_when_given(self):
        fields = build_issue_fields(
            _proposal(), **_JIRA_KWARGS, report_url="https://example.com/report"
        )
        desc_text = fields["description"]["content"][0]["content"][0]["text"]
        assert "https://example.com/report" in desc_text

    def test_uses_resource_id_when_name_is_none(self):
        p = _proposal(finding=_finding(name=None))
        fields = build_issue_fields(p, **_JIRA_KWARGS)
        assert "db-idle-01" in fields["summary"]


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_returns_cost_priority_hash(self):
        fp = fingerprint(_proposal())
        assert fp["cost"] == 340.0
        assert fp["priority"] == "high"
        assert "reason_hash" in fp
        assert len(fp["reason_hash"]) == 6

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
        text = f'some text\n<!-- argus-snapshot: {json.dumps(snap)} -->'
        result = extract_snapshot(text)
        assert result == snap

    def test_returns_none_if_missing(self):
        assert extract_snapshot("no snapshot here") is None

    def test_returns_none_if_malformed_json(self):
        assert extract_snapshot("<!-- argus-snapshot: not-json -->") is None

    def test_roundtrip_from_build_fields(self):
        fields = build_issue_fields(_proposal(), **_JIRA_KWARGS)
        desc_text = fields["description"]["content"][0]["content"][0]["text"]
        extracted = extract_snapshot(desc_text)
        assert extracted is not None
        assert extracted["priority"] == "high"


# ---------------------------------------------------------------------------
# build_update_comment
# ---------------------------------------------------------------------------


class TestBuildUpdateComment:
    def test_includes_date_header(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "aaa"}
        comment = build_update_comment(_proposal(), stored)
        assert "[Argus update" in comment

    def test_shows_cost_change(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "aaa"}
        p = _proposal(estimated_monthly_cost_usd=280.0)
        comment = build_update_comment(p, stored)
        assert "340" in comment
        assert "280" in comment

    def test_shows_priority_change(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "aaa"}
        p = _proposal(finding=_finding(priority="medium"))
        comment = build_update_comment(p, stored)
        assert "high" in comment
        assert "medium" in comment

    def test_shows_reason_when_hash_changes(self):
        stored = {"cost": 340.0, "priority": "high", "reason_hash": "different"}
        comment = build_update_comment(_proposal(), stored)
        assert "CPU averaged" in comment

    def test_no_cost_line_when_unchanged(self):
        fp = fingerprint(_proposal())
        comment = build_update_comment(_proposal(), fp)
        assert "Cost:" not in comment
        assert "Priority:" not in comment
