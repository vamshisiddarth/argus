"""Write testbed/fixtures/synthetic-scan.json.

A hand-made scan report with known mistakes, used to test the scoring harness
offline. It is NOT a recorded scan and says nothing about Argus accuracy.
Re-run after a report schema change:  python testbed/fixtures/make_synthetic_scan.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.models.finding import ResourceFinding
from core.reports.generator import build_report

SCAN_TIME = datetime(2026, 10, 30, 9, 0, 0, tzinfo=timezone.utc)
TAG = "argus-testbed-id"
OUT = Path(__file__).with_name("synthetic-scan.json")

OK_METRICS = {"metrics": {"avg": 0.4}, "metrics_status": "ok", "has_data": True}
NO_METRICS: dict[str, object] = {"metrics_status": "ok", "has_data": True}


def _f(
    tag: str | None,
    rtype: str,
    cost: float,
    basis: str,
    by: str = "model",
    metrics: dict[str, object] | None = None,
    priority: str = "medium",
) -> ResourceFinding:
    rid = f"synthetic-{tag or 'other'}"
    return ResourceFinding(
        resource_id=rid,
        resource_type=rtype,
        cloud="aws",
        region="us-east-1",
        estimated_monthly_cost=cost,
        waste_reason="Synthetic finding.",
        recommendation="Synthetic recommendation.",
        priority=priority,  # type: ignore[arg-type]
        metrics_summary=OK_METRICS if metrics is None else metrics,
        tags={TAG: tag} if tag else {},
        scan_time=SCAN_TIME,
        name=rid,
        cost_basis=basis,
        confidence="medium",
        detected_by=by,
    )


FINDINGS = [
    _f(
        "w-unattached-vol-1",
        "AWS::EC2::Volume",
        1.6,
        "list_price",
        "rule:ebs-volume-unattached",
        NO_METRICS,
    ),
    _f(
        "w-unattached-vol-2",
        "AWS::EC2::Volume",
        8.0,
        "list_price",
        "rule:ebs-volume-unattached",
        NO_METRICS,
    ),
    _f(
        "w-stopped-instance-1",
        "AWS::EC2::Instance",
        0.8,
        "list_price",
        "rule:ec2-instance-stopped",
        NO_METRICS,
    ),
    _f(
        "w-unassociated-eip-1",
        "AWS::EC2::EIP",
        3.65,
        "list_price",
        "rule:elastic-ip-unassociated",
        NO_METRICS,
    ),
    _f(
        "w-unassociated-eip-2",
        "AWS::EC2::EIP",
        3.65,
        "list_price",
        "rule:elastic-ip-unassociated",
        NO_METRICS,
    ),
    _f("w-overprov-iops-1", "AWS::EC2::Volume", 12.0, "model_estimate"),
    _f("w-idle-nat-1", "AWS::EC2::NatGateway", 20.0, "model_estimate"),
    _f("w-idle-lb-1", "AWS::ElasticLoadBalancingV2::LoadBalancer", 0.0, "unknown"),
    _f("d-attached-vol-1", "AWS::EC2::Volume", 1.6, "model_estimate", priority="low"),
    _f(None, "AWS::EC2::Instance", 7.6, "model_estimate", priority="low"),
    _f(None, "AWS::EC2::SecurityGroup", 0.0, "unknown", priority="low"),
]


def main() -> None:
    report = build_report(
        FINDINGS,
        cloud="aws",
        executive_summary=(
            "Synthetic fixture for the scoring harness. Not a recorded scan."
        ),
        accounts_scanned=["000000000000"],
        scan_window={"llm_spent_usd": 1.2},
    )
    report["scan_id"] = "00000000-0000-4000-8000-000000000001"
    report["generated_at"] = SCAN_TIME.isoformat()
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
