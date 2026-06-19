"""
Multi-cloud report aggregation and unified resource taxonomy.

Merges individual per-cloud reports into a single combined report with
normalized resource type names for cross-cloud comparison.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

RESOURCE_TAXONOMY: dict[str, str] = {
    # Compute
    "AWS::EC2::Instance": "Compute Instance",
    "AWS::EC2::NatGateway": "NAT Gateway",
    "AWS::Lambda::Function": "Serverless Function",
    "GCE": "Compute Instance",
    "CloudFunction": "Serverless Function",
    "VirtualMachine": "Compute Instance",
    "AzureFunction": "Serverless Function",
    # Database
    "AWS::RDS::DBInstance": "Relational Database",
    "AWS::RDS::DBCluster": "Database Cluster",
    "CloudSQL": "Relational Database",
    "AlloyDB": "Database Cluster",
    "AzureSQL": "Relational Database",
    "CosmosDB": "NoSQL Database",
    # Cache
    "AWS::ElastiCache::CacheCluster": "Cache Cluster",
    "AWS::ElastiCache::ReplicationGroup": "Cache Cluster",
    "Memorystore": "Cache Cluster",
    "AzureCache": "Cache Cluster",
    # Data warehouse
    "AWS::Redshift::Cluster": "Data Warehouse",
    "BigQuery": "Data Warehouse",
    "Synapse": "Data Warehouse",
    # Search
    "AWS::Elasticsearch::Domain": "Search Service",
    # Storage
    "AWS::EC2::Volume": "Block Storage",
    "PersistentDisk": "Block Storage",
    "ManagedDisk": "Block Storage",
    # Load balancer
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "Load Balancer",
    "LoadBalancer": "Load Balancer",
    "AzureLB": "Load Balancer",
    # Replication
    "AWS::DMS::ReplicationInstance": "Replication Instance",
}


def normalize_resource_type(resource_type: str) -> str:
    return RESOURCE_TAXONOMY.get(resource_type, resource_type)


def merge_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge multiple per-cloud reports into one combined multi-cloud report.

    Each input report is a standard Argus report dict (from build_report()).
    The merged report has:
      - All findings from all clouds, sorted by cost descending
      - Each finding gets a `normalized_type` field
      - Combined totals and executive summary
      - Per-cloud breakdown in `cloud_breakdown`
    """
    if not reports:
        return _empty_merged_report()

    if len(reports) == 1:
        return _enrich_single(reports[0])

    all_findings: list[dict[str, Any]] = []
    clouds: list[str] = []
    accounts: list[str] = []
    total_input_tokens = 0
    total_output_tokens = 0
    summaries: list[str] = []
    cloud_breakdown: list[dict[str, Any]] = []

    for report in reports:
        cloud = report["cloud"]
        clouds.append(cloud)
        accounts.extend(report.get("accounts_scanned", []))
        total_input_tokens += report.get("agent_input_tokens", 0)
        total_output_tokens += report.get("agent_output_tokens", 0)

        if report.get("executive_summary"):
            summaries.append(f"[{cloud.upper()}] {report['executive_summary']}")

        cloud_breakdown.append(
            {
                "cloud": cloud,
                "findings_count": report["findings_count"],
                "total_estimated_waste_usd": report["total_estimated_waste_usd"],
                "scan_id": report["scan_id"],
            }
        )

        for finding in report.get("findings", []):
            enriched = {**finding}
            enriched["normalized_type"] = normalize_resource_type(
                finding["resource_type"]
            )
            all_findings.append(enriched)

    all_findings.sort(key=lambda f: f["estimated_monthly_cost"], reverse=True)
    total_waste = sum(f["estimated_monthly_cost"] for f in all_findings)

    return {
        "schema_version": "1.0",
        "scan_id": str(uuid.uuid4()),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "cloud": "multi",
        "clouds": sorted(set(clouds)),
        "accounts_scanned": accounts,
        "total_estimated_waste_usd": round(total_waste, 2),
        "findings_count": len(all_findings),
        "findings": all_findings,
        "executive_summary": " ".join(summaries),
        "agent_input_tokens": total_input_tokens,
        "agent_output_tokens": total_output_tokens,
        "cloud_breakdown": cloud_breakdown,
    }


def _empty_merged_report() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "scan_id": str(uuid.uuid4()),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "cloud": "multi",
        "clouds": [],
        "accounts_scanned": [],
        "total_estimated_waste_usd": 0.0,
        "findings_count": 0,
        "findings": [],
        "executive_summary": "",
        "agent_input_tokens": 0,
        "agent_output_tokens": 0,
        "cloud_breakdown": [],
    }


def _enrich_single(report: dict[str, Any]) -> dict[str, Any]:
    enriched = {**report}
    enriched["clouds"] = [report["cloud"]]
    enriched["cloud_breakdown"] = [
        {
            "cloud": report["cloud"],
            "findings_count": report["findings_count"],
            "total_estimated_waste_usd": report["total_estimated_waste_usd"],
            "scan_id": report["scan_id"],
        }
    ]
    for finding in enriched.get("findings", []):
        finding["normalized_type"] = normalize_resource_type(
            finding["resource_type"]
        )
    return enriched
