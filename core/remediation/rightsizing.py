"""
Lightweight rightsizing heuristics.

Converts observed metric values from metrics_summary into a human-readable
resize recommendation string that appears on ChangeProposal and in Jira tickets.

No cloud imports — pure Python logic only.
"""

from __future__ import annotations

from core.models.finding import ResourceFinding
from core.remediation.models import Policy

# CPU utilisation metric names we recognise across resource types
_CPU_METRIC_NAMES = {
    # AWS RDS
    "CPUUtilization_avg",
    "CPUUtilization_max",
    "CPUUtilization",
    # AWS EC2
    # AWS Redshift
    # GCP Cloud SQL
    "database/cpu/utilization",
    # GCP GKE / compute
    "kubernetes.io/container/cpu/request_utilization",
    # Azure VM
    "Percentage CPU",
    # Azure SQL
    "dtu_consumption_percent",
    # Azure AKS / GKE clusters
    "node_cpu_usage_percentage",
}

# Standard RDS instance size steps (smallest → largest)
_RDS_TIERS = [
    "db.t3.micro",
    "db.t3.small",
    "db.t3.medium",
    "db.t3.large",
    "db.t3.xlarge",
    "db.t3.2xlarge",
    "db.r6g.large",
    "db.r6g.xlarge",
    "db.r6g.2xlarge",
    "db.r6g.4xlarge",
]

# Standard EC2 general-purpose sizes
_EC2_TIERS = [
    "t3.nano",
    "t3.micro",
    "t3.small",
    "t3.medium",
    "t3.large",
    "t3.xlarge",
    "t3.2xlarge",
    "m6i.large",
    "m6i.xlarge",
    "m6i.2xlarge",
]


def suggest(finding: ResourceFinding, policy: Policy) -> str | None:
    """
    Return a human-readable resize recommendation, or None if not applicable.

    Only fires for resize / reduce_nodes actions.
    Uses metrics_summary to pick an observed CPU value and maps it to a
    recommended tier or node count.
    """
    if policy.action not in ("resize", "reduce_nodes"):
        return None

    metrics = finding.metrics_summary or {}
    cpu_value = _extract_cpu(metrics)

    if policy.action == "reduce_nodes":
        return _suggest_nodes(cpu_value, metrics)

    # resize path
    resource_type = finding.resource_type
    if "RDS" in resource_type or "sql" in resource_type.lower():
        return _suggest_rds_tier(cpu_value)
    if "EC2" in resource_type or "Instance" in resource_type:
        return _suggest_ec2_tier(cpu_value)

    # Generic guidance when we don't have type-specific tiers
    if cpu_value is not None:
        return f"Observed CPU ~{cpu_value:.1f}% — consider downsizing by one tier"

    return None


def _extract_cpu(metrics: dict) -> float | None:
    for key in _CPU_METRIC_NAMES:
        if key in metrics:
            try:
                return float(metrics[key])
            except (TypeError, ValueError):
                continue
    # Fallback: look for any key containing "cpu" or "CPU"
    for key, val in metrics.items():
        if "cpu" in key.lower() or "CPU" in key:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _suggest_rds_tier(cpu_pct: float | None) -> str | None:
    if cpu_pct is None:
        return None
    # Very rough mapping: if CPU < 5% → t3.micro, < 20% → t3.small, etc.
    if cpu_pct < 5:
        return f"Recommend db.t3.micro (observed CPU ~{cpu_pct:.1f}%)"
    if cpu_pct < 15:
        return f"Recommend db.t3.small (observed CPU ~{cpu_pct:.1f}%)"
    if cpu_pct < 30:
        return f"Recommend db.t3.medium (observed CPU ~{cpu_pct:.1f}%)"
    return f"Observed CPU ~{cpu_pct:.1f}% — review current tier"


def _suggest_ec2_tier(cpu_pct: float | None) -> str | None:
    if cpu_pct is None:
        return None
    if cpu_pct < 3:
        return f"Recommend t3.nano or t3.micro (observed CPU ~{cpu_pct:.1f}%)"
    if cpu_pct < 10:
        return f"Recommend t3.small (observed CPU ~{cpu_pct:.1f}%)"
    if cpu_pct < 25:
        return f"Recommend t3.medium (observed CPU ~{cpu_pct:.1f}%)"
    return f"Observed CPU ~{cpu_pct:.1f}% — review current size"


def _suggest_nodes(cpu_pct: float | None, metrics: dict) -> str | None:
    # Try to get current node count from metrics
    node_count: int | None = None
    for key in ("node_count", "nodes", "current_nodes"):
        if key in metrics:
            try:
                node_count = int(metrics[key])
                break
            except (TypeError, ValueError):
                continue

    if cpu_pct is None:
        if node_count and node_count > 1:
            return f"Current {node_count} nodes — consider reducing if workload permits"
        return None

    if cpu_pct < 15 and node_count and node_count > 1:
        # target 60% utilisation
        recommended = max(1, round(node_count * cpu_pct / 100 / 0.6))
        if recommended < node_count:
            return (
                f"Observed CPU ~{cpu_pct:.1f}% across {node_count} nodes — "
                f"recommend reducing to {recommended} node(s)"
            )
    elif cpu_pct < 15:
        return f"Observed CPU ~{cpu_pct:.1f}% — consider reducing node count"

    return None
