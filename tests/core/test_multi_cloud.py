from __future__ import annotations

from core.reports.multi_cloud import merge_reports, normalize_resource_type


def _make_report(
    cloud: str,
    findings: list[dict],
    total_waste: float | None = None,
) -> dict:
    if total_waste is None:
        total_waste = sum(f["estimated_monthly_cost"] for f in findings)
    return {
        "schema_version": "1.0",
        "scan_id": f"scan-{cloud}",
        "generated_at": "2026-06-18T00:00:00+00:00",
        "cloud": cloud,
        "accounts_scanned": [f"{cloud}-account-1"],
        "total_estimated_waste_usd": total_waste,
        "findings_count": len(findings),
        "findings": findings,
        "executive_summary": f"{cloud} has idle resources.",
        "agent_input_tokens": 1000,
        "agent_output_tokens": 500,
    }


def _finding(cloud: str, resource_type: str, cost: float) -> dict:
    return {
        "resource_id": f"{cloud}-{resource_type}-1",
        "resource_type": resource_type,
        "cloud": cloud,
        "region": "us-east-1",
        "name": f"{cloud}-instance",
        "estimated_monthly_cost": cost,
        "waste_reason": "idle",
        "recommendation": "terminate",
        "priority": "high",
        "metrics_summary": {},
        "tags": {},
    }


class TestNormalizeResourceType:
    def test_known_aws_type(self):
        assert normalize_resource_type("AWS::EC2::Instance") == "Compute Instance"

    def test_known_gcp_type(self):
        assert normalize_resource_type("GCE") == "Compute Instance"

    def test_known_azure_type(self):
        assert normalize_resource_type("VirtualMachine") == "Compute Instance"

    def test_unknown_type_passes_through(self):
        assert normalize_resource_type("SomeNewService") == "SomeNewService"

    def test_cross_cloud_equivalence(self):
        assert (
            normalize_resource_type("AWS::EC2::Instance")
            == normalize_resource_type("GCE")
            == normalize_resource_type("VirtualMachine")
            == "Compute Instance"
        )

    def test_database_equivalence(self):
        assert (
            normalize_resource_type("AWS::RDS::DBInstance")
            == normalize_resource_type("CloudSQL")
            == normalize_resource_type("AzureSQL")
            == "Relational Database"
        )


class TestMergeReports:
    def test_empty_list(self):
        result = merge_reports([])
        assert result["cloud"] == "multi"
        assert result["findings_count"] == 0
        assert result["clouds"] == []

    def test_single_report_enriched(self):
        report = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 100.0)])
        result = merge_reports([report])
        assert result["clouds"] == ["aws"]
        assert len(result["cloud_breakdown"]) == 1
        assert result["findings"][0]["normalized_type"] == "Compute Instance"

    def test_two_cloud_merge(self):
        aws = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 200.0)])
        gcp = _make_report("gcp", [_finding("gcp", "GCE", 150.0)])
        result = merge_reports([aws, gcp])

        assert result["cloud"] == "multi"
        assert sorted(result["clouds"]) == ["aws", "gcp"]
        assert result["findings_count"] == 2
        assert result["total_estimated_waste_usd"] == 350.0
        assert result["findings"][0]["estimated_monthly_cost"] == 200.0
        assert result["findings"][1]["estimated_monthly_cost"] == 150.0

    def test_three_cloud_merge(self):
        aws = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 100.0)])
        gcp = _make_report("gcp", [_finding("gcp", "GCE", 200.0)])
        azure = _make_report("azure", [_finding("azure", "VirtualMachine", 300.0)])
        result = merge_reports([aws, gcp, azure])

        assert sorted(result["clouds"]) == ["aws", "azure", "gcp"]
        assert result["findings_count"] == 3
        assert result["total_estimated_waste_usd"] == 600.0

    def test_findings_sorted_by_cost_descending(self):
        aws = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 50.0)])
        gcp = _make_report("gcp", [_finding("gcp", "GCE", 300.0)])
        azure = _make_report("azure", [_finding("azure", "VirtualMachine", 150.0)])
        result = merge_reports([aws, gcp, azure])

        costs = [f["estimated_monthly_cost"] for f in result["findings"]]
        assert costs == [300.0, 150.0, 50.0]

    def test_normalized_types_added(self):
        aws = _make_report("aws", [_finding("aws", "AWS::RDS::DBInstance", 100.0)])
        gcp = _make_report("gcp", [_finding("gcp", "CloudSQL", 80.0)])
        result = merge_reports([aws, gcp])

        types = [f["normalized_type"] for f in result["findings"]]
        assert all(t == "Relational Database" for t in types)

    def test_tokens_aggregated(self):
        aws = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 100.0)])
        gcp = _make_report("gcp", [_finding("gcp", "GCE", 100.0)])
        result = merge_reports([aws, gcp])

        assert result["agent_input_tokens"] == 2000
        assert result["agent_output_tokens"] == 1000

    def test_cloud_breakdown_present(self):
        aws = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 200.0)])
        gcp = _make_report("gcp", [_finding("gcp", "GCE", 100.0)])
        result = merge_reports([aws, gcp])

        assert len(result["cloud_breakdown"]) == 2
        clouds_in_breakdown = {b["cloud"] for b in result["cloud_breakdown"]}
        assert clouds_in_breakdown == {"aws", "gcp"}

    def test_executive_summary_combined(self):
        aws = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 100.0)])
        gcp = _make_report("gcp", [_finding("gcp", "GCE", 100.0)])
        result = merge_reports([aws, gcp])

        assert "[AWS]" in result["executive_summary"]
        assert "[GCP]" in result["executive_summary"]

    def test_accounts_merged(self):
        aws = _make_report("aws", [_finding("aws", "AWS::EC2::Instance", 100.0)])
        gcp = _make_report("gcp", [_finding("gcp", "GCE", 100.0)])
        result = merge_reports([aws, gcp])

        assert "aws-account-1" in result["accounts_scanned"]
        assert "gcp-account-1" in result["accounts_scanned"]
