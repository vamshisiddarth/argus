#!/usr/bin/env python3
"""Demo script for the Argus interactive chat mode.

Exercises ChatSession with a mock AI provider and fake cloud adapter
so you can see the conversation flow without real cloud credentials.

Usage (from the project root, with the venv activated):

    python examples/chat_demo.py

Requires: pip install -e ".[dev]"
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.base import CloudAdapter, MetricSummary, Resource  # noqa: E402
from ai.base import AIProvider, AIResponse, Message, Tool  # noqa: E402
from core.agent.chat import ChatSession  # noqa: E402


class DemoAdapter(CloudAdapter):
    """Returns a small set of plausible resources."""

    def list_resources(self, ignore_regions: list[str] | None = None) -> list[Resource]:
        return [
            Resource(
                resource_id="nat-0abc123",
                resource_type="AWS::EC2::NatGateway",
                cloud="aws",
                region="us-east-1",
                tags={"env": "prod"},
            ),
            Resource(
                resource_id="vol-0def456",
                resource_type="AWS::EC2::Volume",
                cloud="aws",
                region="us-east-1",
                tags={"env": "dev", "Name": "orphaned-data"},
            ),
            Resource(
                resource_id="i-0ghi789",
                resource_type="AWS::EC2::Instance",
                cloud="aws",
                region="us-west-2",
                tags={"env": "staging", "Name": "batch-worker"},
            ),
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
        costs = {"nat-0abc123": 32.50, "vol-0def456": 8.00, "i-0ghi789": 28.40}
        return {rid: costs.get(rid, 0.0) for rid in resource_ids}

    def get_last_activity(
        self, resource_id: str, resource_type: str
    ) -> datetime | None:
        return datetime(2026, 3, 15, tzinfo=timezone.utc)


class DemoAIProvider(AIProvider):
    """Returns canned responses to demonstrate conversation flow."""

    def __init__(self) -> None:
        self._call_count = 0

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        self._call_count += 1
        last_user = next(
            (m.text for m in reversed(messages) if m.role == "user" and m.text), ""
        )

        if "top" in last_user.lower() or "waste" in last_user.lower():
            return AIResponse(
                stop_reason="end_turn",
                text=(
                    "Based on your AWS account, the three largest idle resources are:\n\n"
                    "1. **NAT Gateway nat-0abc123** in us-east-1 — $32.50/mo\n"
                    "   Only 847 bytes transferred in 90 days. Recommendation: delete.\n\n"
                    "2. **EC2 Instance i-0ghi789** in us-west-2 — $28.40/mo\n"
                    "   CPU avg 0.3% over 90 days. Recommendation: stop or downsize.\n\n"
                    "3. **EBS Volume vol-0def456** in us-east-1 — $8.00/mo\n"
                    "   Unattached since 2026-03-15. Recommendation: snapshot and delete.\n\n"
                    "Total estimated monthly waste: **$68.90**"
                ),
                tool_calls=[],
                input_tokens=2847,
                output_tokens=412,
            )

        if "nat" in last_user.lower():
            return AIResponse(
                stop_reason="end_turn",
                text=(
                    "NAT Gateway **nat-0abc123** is almost certainly idle:\n"
                    "- Only 847 bytes out in 90 days (likely health-check noise)\n"
                    "- Cost: $32.50/mo ($0.045/hr + data processing)\n"
                    "- Last meaningful activity: 2026-03-15\n\n"
                    "Recommendation: Delete it. If private subnets still need "
                    "internet access, recreate on demand."
                ),
                tool_calls=[],
                input_tokens=3100,
                output_tokens=280,
            )

        return AIResponse(
            stop_reason="end_turn",
            text=(
                "I found 3 resources in your AWS account. "
                "Ask me about specific resources or say "
                '"what are my top wastes?" to get started.'
            ),
            tool_calls=[],
            input_tokens=1500,
            output_tokens=120,
        )


def main() -> None:
    adapter = DemoAdapter()
    ai = DemoAIProvider()

    session = ChatSession(
        ai_provider=ai,
        cloud_adapter=adapter,
        cloud="aws",
        accounts=[{"id": "123456789012", "name": "demo-account"}],
        ignore_regions=[],
        budget_usd=1.0,
        on_tool_call=lambda name, rid: print(f"  [tool] {name}: {rid}"),
    )

    questions = [
        "What are my top 3 wastes?",
        "Tell me more about that NAT Gateway — is it truly idle?",
        "What else should I look at?",
    ]

    print("=" * 60)
    print("Argus Chat Demo (mock AI — no cloud credentials needed)")
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
