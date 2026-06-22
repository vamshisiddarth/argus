#!/usr/bin/env python3
"""Demo script for the Argus interactive chat mode.

Exercises ChatSession with a mock AI provider and fake cloud adapter
so you can see the conversation flow without real cloud credentials.

Usage (from the project root, with the venv activated):

    python examples/chat_demo.py              # defaults to aws
    python examples/chat_demo.py --cloud gcp
    python examples/chat_demo.py --cloud azure

Requires: pip install -e ".[dev]"
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.base import CloudAdapter, MetricSummary, Resource  # noqa: E402
from ai.base import AIProvider, AIResponse, Message, Tool  # noqa: E402
from core.agent.chat import ChatSession  # noqa: E402

DEMO_RESOURCES: dict[str, list[dict[str, Any]]] = {
    "aws": [
        {
            "id": "nat-0abc123",
            "type": "AWS::EC2::NatGateway",
            "region": "us-east-1",
            "tags": {"env": "prod"},
            "cost": 32.50,
            "label": "NAT Gateway nat-0abc123",
        },
        {
            "id": "vol-0def456",
            "type": "AWS::EC2::Volume",
            "region": "us-east-1",
            "tags": {"env": "dev", "Name": "orphaned-data"},
            "cost": 8.00,
            "label": "EBS Volume vol-0def456",
        },
        {
            "id": "i-0ghi789",
            "type": "AWS::EC2::Instance",
            "region": "us-west-2",
            "tags": {"env": "staging", "Name": "batch-worker"},
            "cost": 28.40,
            "label": "EC2 Instance i-0ghi789",
        },
    ],
    "gcp": [
        {
            "id": "projects/demo/zones/us-central1-a/instances/analytics-worker",
            "type": "compute.googleapis.com/Instance",
            "region": "us-central1",
            "tags": {"env": "prod"},
            "cost": 45.60,
            "label": "GCE Instance analytics-worker",
        },
        {
            "id": "projects/demo/zones/us-central1-a/disks/orphaned-disk",
            "type": "compute.googleapis.com/Disk",
            "region": "us-central1",
            "tags": {"env": "dev"},
            "cost": 12.00,
            "label": "Persistent Disk orphaned-disk",
        },
        {
            "id": "projects/demo/instances/staging-sql",
            "type": "sqladmin.googleapis.com/Instance",
            "region": "us-central1",
            "tags": {"env": "staging"},
            "cost": 72.80,
            "label": "Cloud SQL staging-sql",
        },
    ],
    "azure": [
        {
            "id": (
                "/subscriptions/abc/resourceGroups/rg"
                "/providers/Microsoft.Compute"
                "/virtualMachines/analytics-vm"
            ),
            "type": "Microsoft.Compute/virtualMachines",
            "region": "eastus",
            "tags": {"Environment": "prod"},
            "cost": 55.20,
            "label": "VM analytics-vm",
        },
        {
            "id": (
                "/subscriptions/abc/resourceGroups/rg"
                "/providers/Microsoft.Compute"
                "/disks/orphaned-disk"
            ),
            "type": "Microsoft.Compute/disks",
            "region": "eastus",
            "tags": {"Environment": "dev"},
            "cost": 15.00,
            "label": "Managed Disk orphaned-disk",
        },
        {
            "id": (
                "/subscriptions/abc/resourceGroups/rg"
                "/providers/Microsoft.Sql/servers/srv"
                "/databases/staging-db"
            ),
            "type": "Microsoft.Sql/servers/databases",
            "region": "eastus",
            "tags": {"Environment": "staging"},
            "cost": 38.40,
            "label": "SQL Database staging-db",
        },
    ],
}

DEMO_ACCOUNTS: dict[str, list[dict[str, str]]] = {
    "aws": [{"id": "123456789012", "name": "demo-account"}],
    "gcp": [{"id": "demo-project-123", "name": "demo-project-123"}],
    "azure": [{"id": "a1b2c3d4-e5f6-7890", "name": "a1b2c3d4-e5f6-7890"}],
}


class DemoAdapter(CloudAdapter):
    """Returns a small set of plausible resources for any cloud."""

    def __init__(self, cloud: str) -> None:
        self._cloud = cloud
        self._resources = DEMO_RESOURCES[cloud]

    def list_resources(self, ignore_regions: list[str] | None = None) -> list[Resource]:
        return [
            Resource(
                resource_id=r["id"],
                resource_type=r["type"],
                cloud=self._cloud,
                region=r["region"],
                tags=r["tags"],
            )
            for r in self._resources
        ]

    def get_metrics(
        self, resource_id: str, resource_type: str, days: int = 90
    ) -> MetricSummary:
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={"cpu_avg": 0.3, "bytes_out_total": 847},
        )

    def get_cost(self, resource_ids: list[str], days: int = 30) -> dict[str, float]:
        costs = {r["id"]: r["cost"] for r in self._resources}
        return {rid: costs.get(rid, 0.0) for rid in resource_ids}

    def get_last_activity(
        self, resource_id: str, resource_type: str
    ) -> datetime | None:
        return datetime(2026, 3, 15, tzinfo=timezone.utc)


class DemoAIProvider(AIProvider):
    """Returns canned responses to demonstrate conversation flow."""

    def __init__(self, cloud: str) -> None:
        self._cloud = cloud
        self._resources = DEMO_RESOURCES[cloud]

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        last_user = next(
            (m.text for m in reversed(messages) if m.role == "user" and m.text), ""
        )
        cloud_upper = self._cloud.upper()
        r = self._resources

        if "top" in last_user.lower() or "waste" in last_user.lower():
            lines = [
                f"Based on your {cloud_upper} account,"
                " the largest idle resources are:\n"
            ]
            for i, res in enumerate(r, 1):
                label = res["label"]
                region = res["region"]
                cost = res["cost"]
                lines.append(f"{i}. **{label}** in {region} — ${cost:.2f}/mo")
            total = sum(res["cost"] for res in r)
            lines.append(f"\nTotal estimated monthly waste: **${total:.2f}**")
            return AIResponse(
                stop_reason="end_turn",
                text="\n".join(lines),
                tool_calls=[],
                input_tokens=2847,
                output_tokens=412,
            )

        if any(keyword in last_user.lower() for keyword in ("more", "detail", "idle")):
            top = r[0]
            return AIResponse(
                stop_reason="end_turn",
                text=(
                    f"**{top['label']}** is almost certainly idle:\n"
                    f"- CPU avg 0.3% over 90 days\n"
                    f"- Cost: ${top['cost']:.2f}/mo\n"
                    f"- Last meaningful activity: 2026-03-15\n\n"
                    f"Recommendation: Clean it up."
                ),
                tool_calls=[],
                input_tokens=3100,
                output_tokens=280,
            )

        return AIResponse(
            stop_reason="end_turn",
            text=(
                f"I found {len(r)} resources in your {cloud_upper} account. "
                f"Ask me about specific resources or say "
                f'"what are my top wastes?" to get started.'
            ),
            tool_calls=[],
            input_tokens=1500,
            output_tokens=120,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Argus chat demo")
    parser.add_argument(
        "--cloud",
        default="aws",
        choices=["aws", "gcp", "azure"],
    )
    args = parser.parse_args()

    cloud = args.cloud
    adapter = DemoAdapter(cloud)
    ai = DemoAIProvider(cloud)

    session = ChatSession(
        ai_provider=ai,
        cloud_adapter=adapter,
        cloud=cloud,
        accounts=DEMO_ACCOUNTS[cloud],
        ignore_regions=[],
        budget_usd=1.0,
        on_tool_call=lambda name, rid: print(f"  [tool] {name}: {rid}"),
    )

    questions = [
        "What are my top wastes?",
        "Tell me more about the first one — is it truly idle?",
        "What else should I look at?",
    ]

    print("=" * 60)
    print(f"Argus Chat Demo — {cloud.upper()} (mock AI, no credentials needed)")
    print("=" * 60)

    for q in questions:
        print(f"\nargus> {q}")
        response = session.ask(q)
        print(f"\n{response.text}")
        print(
            f"\n  [{response.turn_input_tokens:,} in / "
            f"{response.turn_output_tokens:,} out, "
            f"${response.turn_cost_usd:.4f}]"
        )
        print("-" * 60)

    summary = session.cost_summary
    print(
        f"\nSession total: {summary['total_input_tokens']:,} in / "
        f"{summary['total_output_tokens']:,} out | "
        f"${summary['estimated_cost_usd']:.4f} / "
        f"${summary['budget_usd']:.2f} budget"
    )


if __name__ == "__main__":
    main()
