from __future__ import annotations

from datetime import datetime, timezone

from core.models.finding import ResourceFinding
from core.reports.comparison import compare_scans


def _make_finding(resource_id: str, cost: float = 10.0) -> ResourceFinding:
    return ResourceFinding(
        resource_id=resource_id,
        resource_type="EC2",
        cloud="aws",
        region="us-east-1",
        estimated_monthly_cost=cost,
        waste_reason="idle",
        recommendation="delete",
        priority="high",
        metrics_summary={},
        tags={},
        scan_time=datetime.now(tz=timezone.utc),
    )


def _make_prev_report(resource_ids: list[str]) -> dict:
    return {
        "scan_id": "prev-scan-id",
        "findings": [{"resource_id": rid} for rid in resource_ids],
    }


class TestCompareScans:
    def test_no_previous_report_all_new(self):
        findings = [_make_finding("r1"), _make_finding("r2")]
        labelled, diff = compare_scans(findings, None)
        assert all(f.status == "new" for f in labelled)
        assert diff["previous_scan_id"] is None
        assert diff["new_findings"] == 2
        assert diff["recurring_findings"] == 0
        assert diff["resolved_findings"] == 0

    def test_recurring_findings(self):
        findings = [_make_finding("r1"), _make_finding("r2")]
        prev = _make_prev_report(["r1", "r2"])
        labelled, diff = compare_scans(findings, prev)
        assert all(f.status == "recurring" for f in labelled)
        assert diff["recurring_findings"] == 2
        assert diff["new_findings"] == 0
        assert diff["resolved_findings"] == 0

    def test_resolved_findings(self):
        findings = [_make_finding("r1")]
        prev = _make_prev_report(["r1", "r2", "r3"])
        labelled, diff = compare_scans(findings, prev)
        assert diff["resolved_findings"] == 2
        assert sorted(diff["resolved_resource_ids"]) == ["r2", "r3"]

    def test_mixed_new_recurring_resolved(self):
        findings = [_make_finding("r1"), _make_finding("r3")]
        prev = _make_prev_report(["r1", "r2"])
        labelled, diff = compare_scans(findings, prev)

        status_map = {f.resource_id: f.status for f in labelled}
        assert status_map["r1"] == "recurring"
        assert status_map["r3"] == "new"
        assert diff["new_findings"] == 1
        assert diff["recurring_findings"] == 1
        assert diff["resolved_findings"] == 1
        assert diff["resolved_resource_ids"] == ["r2"]
        assert diff["previous_scan_id"] == "prev-scan-id"

    def test_empty_current_all_resolved(self):
        prev = _make_prev_report(["r1", "r2"])
        labelled, diff = compare_scans([], prev)
        assert labelled == []
        assert diff["resolved_findings"] == 2
        assert diff["new_findings"] == 0

    def test_status_in_to_dict(self):
        f = _make_finding("r1")
        f.status = "recurring"
        d = f.to_dict()
        assert d["status"] == "recurring"

    def test_status_from_dict(self):
        data = {
            "resource_id": "r1",
            "resource_type": "EC2",
            "cloud": "aws",
            "region": "us-east-1",
            "estimated_monthly_cost": 10.0,
            "waste_reason": "idle",
            "recommendation": "delete",
            "priority": "high",
            "status": "recurring",
        }
        f = ResourceFinding.from_dict(data, datetime.now(tz=timezone.utc))
        assert f.status == "recurring"

    def test_scan_diff_in_report(self):
        from core.reports.generator import build_report

        findings = [_make_finding("r1")]
        prev = _make_prev_report(["r1", "r2"])
        findings, scan_diff = compare_scans(findings, prev)
        report = build_report(
            findings, cloud="aws", executive_summary="test", scan_diff=scan_diff
        )
        assert report["scan_diff"]["previous_scan_id"] == "prev-scan-id"
        assert report["scan_diff"]["resolved_findings"] == 1
        assert report["findings"][0]["status"] == "recurring"
