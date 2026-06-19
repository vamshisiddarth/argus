"""
Report schema validation tests.

Verify that build_report produces structurally valid JSON reports with
correct types, required fields, and consistent aggregations. Ignores
AI-generated free-text (executive_summary, waste_reason, recommendation)
since those change with model/prompt updates.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models.finding import ResourceFinding
from core.reports.comparison import compare_scans
from core.reports.generator import build_report, build_slack_payload

SCAN_TIME = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_finding(**overrides) -> ResourceFinding:
    defaults = {
        "resource_id": "i-0abc123",
        "resource_type": "EC2",
        "cloud": "aws",
        "region": "us-east-1",
        "estimated_monthly_cost": 150.0,
        "waste_reason": "CPU < 1%",
        "recommendation": "Terminate",
        "priority": "high",
        "metrics_summary": {"cpu_avg": 0.5},
        "tags": {"Env": "dev"},
        "scan_time": SCAN_TIME,
        "name": "test-instance",
    }
    defaults.update(overrides)
    return ResourceFinding(**defaults)


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

REQUIRED_REPORT_FIELDS = {
    "schema_version",
    "scan_id",
    "generated_at",
    "cloud",
    "accounts_scanned",
    "total_estimated_waste_usd",
    "findings_count",
    "findings",
    "executive_summary",
    "agent_input_tokens",
    "agent_output_tokens",
    "estimated_agent_cost_usd",
    "scan_diff",
}

REQUIRED_FINDING_FIELDS = {
    "resource_id",
    "resource_type",
    "cloud",
    "region",
    "estimated_monthly_cost",
    "waste_reason",
    "recommendation",
    "priority",
    "metrics_summary",
    "tags",
    "scan_time",
    "status",
}


@pytest.mark.integration
class TestReportSchema:
    def test_report_has_all_required_fields(self):
        findings = [_make_finding()]
        report = build_report(
            findings, cloud="aws", executive_summary="Test.",
            accounts_scanned=["123456789012"],
            agent_input_tokens=1000, agent_output_tokens=500,
        )
        missing = REQUIRED_REPORT_FIELDS - set(report.keys())
        assert not missing, f"Missing report fields: {missing}"

    def test_findings_have_all_required_fields(self):
        findings = [_make_finding()]
        report = build_report(findings, cloud="aws", executive_summary="Test.")
        for f in report["findings"]:
            missing = REQUIRED_FINDING_FIELDS - set(f.keys())
            assert not missing, f"Missing finding fields: {missing}"

    def test_findings_sorted_by_cost_descending(self):
        findings = [
            _make_finding(resource_id="cheap", estimated_monthly_cost=10.0),
            _make_finding(resource_id="expensive", estimated_monthly_cost=500.0),
            _make_finding(resource_id="medium", estimated_monthly_cost=100.0),
        ]
        report = build_report(findings, cloud="aws", executive_summary="Test.")
        costs = [f["estimated_monthly_cost"] for f in report["findings"]]
        assert costs == sorted(costs, reverse=True)

    def test_total_waste_matches_sum_of_findings(self):
        findings = [
            _make_finding(resource_id="a", estimated_monthly_cost=100.0),
            _make_finding(resource_id="b", estimated_monthly_cost=200.0),
            _make_finding(resource_id="c", estimated_monthly_cost=50.0),
        ]
        report = build_report(findings, cloud="aws", executive_summary="Test.")
        assert report["total_estimated_waste_usd"] == 350.0
        assert report["findings_count"] == 3

    def test_empty_findings_produce_valid_report(self):
        report = build_report([], cloud="gcp", executive_summary="Nothing found.")
        assert report["findings_count"] == 0
        assert report["total_estimated_waste_usd"] == 0
        assert report["findings"] == []

    def test_token_counts_flow_into_report(self):
        report = build_report(
            [_make_finding()], cloud="aws", executive_summary="Test.",
            agent_input_tokens=5000, agent_output_tokens=2000,
        )
        assert report["agent_input_tokens"] == 5000
        assert report["agent_output_tokens"] == 2000
        assert report["estimated_agent_cost_usd"] > 0

    def test_agent_cost_estimate_is_reasonable(self):
        report = build_report(
            [], cloud="aws", executive_summary="Test.",
            agent_input_tokens=1_000_000, agent_output_tokens=100_000,
        )
        # 1M input * $3/M + 100K output * $15/M = $3 + $1.5 = $4.5
        assert report["estimated_agent_cost_usd"] == 4.5

    def test_scan_id_is_uuid_format(self):
        report = build_report([], cloud="aws", executive_summary="Test.")
        import uuid
        uuid.UUID(report["scan_id"])  # raises if invalid

    def test_generated_at_is_iso_format(self):
        report = build_report([], cloud="aws", executive_summary="Test.")
        datetime.fromisoformat(report["generated_at"])  # raises if invalid

    def test_cloud_field_matches_input(self):
        for cloud in ("aws", "gcp", "azure"):
            report = build_report([], cloud=cloud, executive_summary="Test.")
            assert report["cloud"] == cloud

    def test_priority_values_are_valid(self):
        for priority in ("high", "medium", "low"):
            findings = [_make_finding(priority=priority)]
            report = build_report(findings, cloud="aws", executive_summary="Test.")
            assert report["findings"][0]["priority"] == priority


# ---------------------------------------------------------------------------
# Slack payload structure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSlackPayloadSchema:
    def test_payload_has_blocks(self):
        report = build_report(
            [_make_finding()], cloud="aws", executive_summary="Test.",
            accounts_scanned=["123"],
        )
        payload = build_slack_payload(report)
        assert "blocks" in payload
        assert isinstance(payload["blocks"], list)
        assert len(payload["blocks"]) > 0

    def test_header_block_exists(self):
        report = build_report(
            [_make_finding()], cloud="aws", executive_summary="Test.",
            accounts_scanned=["123"],
        )
        payload = build_slack_payload(report)
        headers = [b for b in payload["blocks"] if b.get("type") == "header"]
        assert len(headers) == 1

    def test_report_url_adds_button(self):
        report = build_report([], cloud="aws", executive_summary="Test.")
        payload_no_url = build_slack_payload(report)
        payload_with_url = build_slack_payload(report, report_url="https://example.com/report.html")

        actions_no = [b for b in payload_no_url["blocks"] if b.get("type") == "actions"]
        actions_with = [b for b in payload_with_url["blocks"] if b.get("type") == "actions"]

        assert len(actions_with) >= 1
        urls = [
            e["url"]
            for a in actions_with
            for e in a.get("elements", [])
            if "url" in e
        ]
        assert "https://example.com/report.html" in urls

    def test_empty_findings_still_valid_payload(self):
        report = build_report([], cloud="azure", executive_summary="Clean.")
        payload = build_slack_payload(report)
        assert "blocks" in payload


# ---------------------------------------------------------------------------
# Scan comparison
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestScanComparison:
    def test_first_scan_all_new(self):
        findings = [_make_finding(resource_id="a"), _make_finding(resource_id="b")]
        labelled, diff = compare_scans(findings, None)
        assert all(f.status == "new" for f in labelled)
        assert diff["new_findings"] == 2
        assert diff["recurring_findings"] == 0
        assert diff["resolved_findings"] == 0

    def test_recurring_and_new(self):
        prev_report = {
            "scan_id": "prev-scan",
            "findings": [
                {"resource_id": "a"},
                {"resource_id": "b"},
            ],
        }
        findings = [
            _make_finding(resource_id="a"),
            _make_finding(resource_id="c"),
        ]
        labelled, diff = compare_scans(findings, prev_report)
        statuses = {f.resource_id: f.status for f in labelled}
        assert statuses["a"] == "recurring"
        assert statuses["c"] == "new"
        assert diff["new_findings"] == 1
        assert diff["recurring_findings"] == 1
        assert diff["resolved_findings"] == 1
        assert "b" in diff["resolved_resource_ids"]

    def test_all_resolved(self):
        prev_report = {
            "scan_id": "prev-scan",
            "findings": [
                {"resource_id": "a"},
                {"resource_id": "b"},
            ],
        }
        labelled, diff = compare_scans([], prev_report)
        assert diff["resolved_findings"] == 2
        assert diff["new_findings"] == 0

    def test_diff_summary_schema(self):
        _, diff = compare_scans([_make_finding()], None)
        required = {"previous_scan_id", "new_findings", "recurring_findings",
                     "resolved_findings", "resolved_resource_ids"}
        assert required.issubset(set(diff.keys()))
