"""Write examples/sample-board.html: the static board page built from made-up data.

The data is synthetic (a seeded generator, no real account). Regenerate after a
report schema or board change:  python examples/make_sample_board.py
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.models.finding import ResourceFinding
from core.reports.board import build_board_html
from core.reports.generator import build_report

SCAN_TIME = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
TEAMS = ["platform", "payments", "data", "growth", "security"]
OUT = Path(__file__).with_name("sample-board.html")


def _findings() -> list[ResourceFinding]:
    rng = random.Random(7)
    out: list[ResourceFinding] = []

    def add(
        n: int,
        rtype: str,
        prefix: str,
        rec: str,
        reason: str,
        cost: float,
        basis: str,
        conf: str,
        by: str = "model",
        prio: str = "medium",
        review: bool = False,
    ) -> None:
        for i in range(n):
            tags = {"Team": rng.choice(TEAMS)} if rng.random() < 0.75 else {}
            price = round(cost * rng.uniform(0.6, 1.6), 2) if cost else 0.0
            out.append(
                ResourceFinding(
                    resource_id=f"{prefix}-{rng.randrange(16**8):08x}",
                    resource_type=rtype,
                    cloud="aws",
                    region="eu-west-1",
                    estimated_monthly_cost=price,
                    waste_reason=reason,
                    recommendation=rec,
                    priority=prio,  # type: ignore[arg-type]
                    metrics_summary={
                        "metrics": {"avg": 0.4} if by == "model" else {},
                        "metrics_status": "ok",
                        "last_activity_checked": rng.random() < 0.3,
                    },
                    tags=tags,
                    scan_time=SCAN_TIME,
                    name=f"prod-{prefix}-{i}" if review else f"{prefix}-{i}",
                    cost_basis=basis if price else "unknown",
                    confidence=conf,
                    detected_by=by,
                    account_id="123456789012",
                )
            )

    add(
        34,
        "AWS::EC2::Volume",
        "vol",
        "Snapshot it, then delete the volume.",
        "Unattached for months.",
        9,
        "list_price",
        "high",
        "rule:ebs-volume-unattached",
    )
    add(
        14,
        "AWS::EC2::Instance",
        "i",
        "Terminate the instance and delete its disks.",
        "Stopped for over 30 days; disks still bill.",
        6,
        "list_price",
        "high",
        "rule:ec2-instance-stopped",
    )
    add(
        12,
        "AWS::EC2::EIP",
        "eipalloc",
        "Release the address.",
        "Not associated with anything.",
        3.65,
        "list_price",
        "high",
        "rule:elastic-ip-unassociated",
    )
    add(
        9,
        "rds:snapshot",
        "snap-rds",
        "Delete after confirming the migration finished.",
        "Manual snapshot with no recent restore.",
        40,
        "model_estimate",
        "medium",
    )
    add(
        7,
        "ec2:snapshot",
        "snap",
        "Delete if the source volume is gone.",
        "Source volume no longer exists.",
        6,
        "model_estimate",
        "medium",
    )
    add(
        11,
        "logs:log-group",
        "lg",
        "Set a 30 day retention on the log group.",
        "Never expires; storage grows.",
        12,
        "model_estimate",
        "medium",
    )
    add(
        5,
        "AWS::EC2::NatGateway",
        "nat",
        "Review whether the gateway is still needed.",
        "Very little traffic in 90 days.",
        33,
        "model_estimate",
        "low",
    )
    add(
        4,
        "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "alb",
        "Verify with the owner, then delete.",
        "No healthy targets.",
        16,
        "model_estimate",
        "low",
    )
    add(
        9,
        "AWS::ECS::Service",
        "svc",
        "Review the service and confirm it is used.",
        "Zero requests in 30 days.",
        0,
        "unknown",
        "low",
    )
    add(
        6,
        "AWS::RDS::DBInstance",
        "db",
        "Right-size to a smaller instance class.",
        "CPU under 8% for 90 days.",
        310,
        "model_estimate",
        "medium",
        prio="high",
    )
    add(
        4,
        "AWS::EC2::Instance",
        "billing",
        "Review before any change.",
        "Low CPU but the name suggests production.",
        1400,
        "model_estimate",
        "low",
        prio="high",
        review=True,
    )
    add(
        3,
        "AWS::EC2::Volume",
        "dbvol",
        "Delete after a snapshot.",
        "Unattached.",
        120,
        "model_estimate",
        "medium",
        review=True,
    )
    add(
        3,
        "ec2:client-vpn-endpoint",
        "cvpn",
        "Delete endpoints with no connections.",
        "No connections in 14 days.",
        73,
        "billed",
        "high",
    )
    add(
        2,
        "AWS::OpenSearchService::Domain",
        "search",
        "Review the domain size.",
        "Low utilisation.",
        540,
        "model_estimate",
        "low",
        prio="high",
    )
    return out


def build() -> str:
    report = build_report(
        _findings(),
        cloud="aws",
        executive_summary="Sample data for the board report.",
        accounts_scanned=["123456789012"],
        agent_input_tokens=205310,
        agent_output_tokens=55872,
        coverage={
            "discovered": 1420,
            "analysed": 1418,
            "dropped": 2,
            "truncated": False,
            "free_config_skipped": 3200,
            "regions_covered": ["eu-west-1", "us-east-1", "eu-central-1"],
        },
        scan_window={
            "metrics_lookback_days": 90,
            "llm_spent_usd": 1.62,
            "llm_budget_usd": 2.0,
            "llm_estimate_usd": 1.18,
            "llm_calibration": {"calls": 24},
        },
        preflight={
            "skipped": False,
            "accounts": [
                {
                    "account_id": "123456789012",
                    "skipped": False,
                    "checks": [
                        {
                            "code": "P8_COST_DATA",
                            "status": "warn",
                            "message": "Resource-level cost data is not enabled; "
                            "per-resource costs are unavailable.",
                        }
                    ],
                }
            ],
        },
    )
    report["scan_id"] = "00000000-0000-4000-8000-000000000002"
    report["generated_at"] = SCAN_TIME.isoformat()
    return build_board_html(report)


def main(out: Path = OUT) -> None:
    out.write_text(build(), encoding="ascii")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
