"""
Shared fixtures for integration tests.

Provides pre-seeded mock adapters and AI providers that return realistic
data without hitting real cloud APIs. These test the full orchestration
path: CLI → AgentLoop → adapter → report generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from adapters.base import MetricSummary, Resource
from ai.base import AIResponse, ToolCall


# ---------------------------------------------------------------------------
# Realistic resource sets per cloud
# ---------------------------------------------------------------------------

AWS_RESOURCES = [
    Resource(
        resource_id="i-0abc123def456789a",
        resource_type="AWS::EC2::Instance",
        cloud="aws",
        region="us-east-1",
        name="web-prod-01",
        tags={"Env": "prod", "Team": "platform"},
    ),
    Resource(
        resource_id="i-0bbb222ccc333ddd4",
        resource_type="AWS::EC2::Instance",
        cloud="aws",
        region="us-east-1",
        name="dev-scratch",
        tags={"Env": "dev"},
    ),
    Resource(
        resource_id="arn:aws:rds:us-east-1:123456789012:db:idle-postgres",
        resource_type="AWS::RDS::DBInstance",
        cloud="aws",
        region="us-east-1",
        name="idle-postgres",
        tags={"Env": "staging"},
    ),
    Resource(
        resource_id="arn:aws:elasticache:us-west-2:123456789012:cluster:unused-redis",
        resource_type="AWS::ElastiCache::CacheCluster",
        cloud="aws",
        region="us-west-2",
        name="unused-redis",
        tags={},
    ),
]

GCP_RESOURCES = [
    Resource(
        resource_id="projects/my-proj/zones/us-central1-a/instances/idle-vm-1",
        resource_type="compute.googleapis.com/Instance",
        cloud="gcp",
        region="us-central1",
        name="idle-vm-1",
        tags={"env": "dev"},
    ),
    Resource(
        resource_id="projects/my-proj/instances/unused-sql",
        resource_type="sqladmin.googleapis.com/Instance",
        cloud="gcp",
        region="us-central1",
        name="unused-sql",
        tags={},
    ),
]

AZURE_RESOURCES = [
    Resource(
        resource_id="/subscriptions/sub-1/resourceGroups/rg-dev/providers/Microsoft.Compute/virtualMachines/idle-vm",
        resource_type="Microsoft.Compute/virtualMachines",
        cloud="azure",
        region="eastus",
        name="idle-vm",
        tags={"env": "dev"},
    ),
    Resource(
        resource_id="/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Sql/servers/unused-sql/databases/mydb",
        resource_type="Microsoft.Sql/servers/databases",
        cloud="azure",
        region="eastus",
        name="unused-sql-mydb",
        tags={"env": "prod"},
    ),
]

# Costs per resource ID (USD/month)
COSTS = {
    "i-0abc123def456789a": 156.0,
    "i-0bbb222ccc333ddd4": 45.0,
    "arn:aws:rds:us-east-1:123456789012:db:idle-postgres": 230.0,
    "arn:aws:elasticache:us-west-2:123456789012:cluster:unused-redis": 67.0,
    "projects/my-proj/zones/us-central1-a/instances/idle-vm-1": 89.0,
    "projects/my-proj/instances/unused-sql": 312.0,
    "/subscriptions/sub-1/resourceGroups/rg-dev/providers/Microsoft.Compute/virtualMachines/idle-vm": 73.0,
    "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Sql/servers/unused-sql/databases/mydb": 198.0,
}


def _make_metrics(resource_id: str, resource_type: str) -> MetricSummary:
    return MetricSummary(
        resource_id=resource_id,
        resource_type=resource_type,
        period_days=90,
        metrics={"cpu_avg_pct": 0.8, "network_in_bytes": 1024},
        has_data=True,
    )


LAST_ACTIVITY = datetime(2025, 3, 15, tzinfo=timezone.utc)


def _make_adapter(resources: list[Resource]) -> MagicMock:
    adapter = MagicMock()
    adapter.list_resources.return_value = resources
    adapter.get_cost.return_value = {r.resource_id: COSTS.get(r.resource_id, 0) for r in resources}
    adapter.get_metrics.side_effect = lambda resource_id, resource_type, **kw: _make_metrics(resource_id, resource_type)
    adapter.get_last_activity.return_value = LAST_ACTIVITY
    return adapter


def _make_submit_ai(cloud: str, resources: list[Resource]) -> MagicMock:
    """Create a mock AI that lists resources then submits findings for all."""
    ai = MagicMock()

    list_response = AIResponse(
        stop_reason="tool_use",
        text="Listing resources.",
        tool_calls=[
            ToolCall(id="tc_list", name="list_resources", arguments={"ignore_regions": []})
        ],
        input_tokens=800,
        output_tokens=300,
    )

    findings = []
    for r in resources:
        cost = COSTS.get(r.resource_id, 10.0)
        findings.append({
            "resource_id": r.resource_id,
            "resource_type": r.resource_type,
            "region": r.region,
            "name": r.name,
            "estimated_monthly_cost": cost,
            "waste_reason": f"CPU utilization < 1% for 90 days",
            "recommendation": "Terminate or downsize",
            "priority": "high" if cost > 100 else "medium",
            "metrics_summary": {"cpu_avg_pct": 0.8},
            "tags": r.tags,
        })

    submit_response = AIResponse(
        stop_reason="tool_use",
        text="Analysis complete.",
        tool_calls=[
            ToolCall(
                id="tc_submit",
                name="submit_findings",
                arguments={
                    "findings": findings,
                    "executive_summary": f"Found {len(findings)} idle resources in {cloud.upper()}.",
                },
            )
        ],
        input_tokens=2000,
        output_tokens=1500,
    )

    ai.chat.side_effect = [list_response, submit_response]
    return ai


@pytest.fixture
def aws_adapter():
    return _make_adapter(AWS_RESOURCES)


@pytest.fixture
def gcp_adapter():
    return _make_adapter(GCP_RESOURCES)


@pytest.fixture
def azure_adapter():
    return _make_adapter(AZURE_RESOURCES)


@pytest.fixture
def aws_ai():
    return _make_submit_ai("aws", AWS_RESOURCES)


@pytest.fixture
def gcp_ai():
    return _make_submit_ai("gcp", GCP_RESOURCES)


@pytest.fixture
def azure_ai():
    return _make_submit_ai("azure", AZURE_RESOURCES)
