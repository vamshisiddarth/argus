from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from adapters.base import CloudAdapter
from ai.base import AIProvider, Message, Tool, ToolCall, ToolResult
from core.agent.prompts import build_system_prompt, build_tool_schemas
from core.models.finding import ResourceFinding

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 50

# Maximum number of resources handed to the AI after pre-filtering by cost.
# Resources beyond this limit are silently dropped (they have near-zero cost
# and would only consume context window without adding value).
# Override via MAX_RESOURCES_PER_SCAN env var for large accounts.
import os as _os
MAX_RESOURCES_PER_SCAN: int = int(_os.environ.get("MAX_RESOURCES_PER_SCAN", "200"))


class AgentLoop:
    """
    ReAct (Reason + Act) agent loop.

    The AI decides which tools to call and in what order. This class:
      - Manages the conversation history
      - Dispatches tool calls to the CloudAdapter
      - Terminates when the AI calls submit_findings
      - Never contains cloud-specific logic
    """

    def __init__(self, ai_provider: AIProvider, cloud_adapter: CloudAdapter) -> None:
        self._ai = ai_provider
        self._adapter = cloud_adapter
        self._tools: list[Tool] = [
            Tool(
                name=t["name"],
                description=t["description"],
                input_schema=t["input_schema"],
            )
            for t in build_tool_schemas()
        ]

    def run(
        self,
        cloud: str,
        ignore_regions: list[str],
        accounts: list[dict[str, Any]],
    ) -> tuple[list[ResourceFinding], str]:
        """
        Run the full agent analysis for one cloud + account combination.

        Returns:
            (findings, executive_summary)
            findings: ResourceFinding list sorted by estimated_monthly_cost desc
            executive_summary: AI-written 3-5 sentence summary for managers
        """
        system_prompt = build_system_prompt(cloud=cloud, ignore_regions=ignore_regions, accounts=accounts)

        # ------------------------------------------------------------------
        # Phase 0 — pre-filter (outside AI context, no tokens consumed)
        # Fetch all resources + batch cost, then hand only the top-N by cost
        # to the agent. This keeps context small regardless of account size.
        # ------------------------------------------------------------------
        prefiltered = self._prefilter_resources(ignore_regions)

        messages: list[Message] = [
            Message(role="user", text="Begin your cloud cost analysis now.")
        ]

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info("agent_iteration", extra={"iteration": iteration})

            response = self._ai.chat(messages, self._tools, system_prompt=system_prompt)

            if response.stop_reason == "tool_use":
                # Check first — submit_findings terminates the loop immediately
                for tc in response.tool_calls:
                    if tc.name == "submit_findings":
                        logger.info(
                            "agent_complete",
                            extra={"findings_count": len(tc.arguments.get("findings", []))},
                        )
                        return _parse_findings(tc.arguments, cloud=cloud)

                # Persist the assistant turn before executing tools
                messages.append(
                    Message(
                        role="assistant",
                        text=response.text,
                        tool_calls=response.tool_calls,
                    )
                )

                # Execute every tool call; collect all results into one user turn
                tool_results: list[ToolResult] = []
                for tc in response.tool_calls:
                    content, is_error = self._execute(tc)
                    logger.info(
                        "tool_executed",
                        extra={"tool": tc.name, "is_error": is_error},
                    )
                    tool_results.append(
                        ToolResult(
                            tool_call_id=tc.id,
                            content=content,
                            is_error=is_error,
                        )
                    )

                messages.append(Message(role="user", tool_results=tool_results))

            else:
                # end_turn or max_tokens without submit_findings — shouldn't happen
                # if the prompt is working, but handle gracefully
                logger.warning(
                    "agent_stopped_without_findings",
                    extra={"stop_reason": response.stop_reason},
                )
                return [], response.text or ""

        raise RuntimeError(
            f"Agent loop exceeded {MAX_ITERATIONS} iterations without submitting findings. "
            "Check the system prompt or increase MAX_ITERATIONS."
        )

    def _prefilter_resources(self, ignore_regions: list[str]) -> list[dict]:
        """
        Phase 0: enumerate all resources + batch-fetch cost outside the AI loop.

        Steps:
          1. list_resources — discovers all billable resources
          2. get_cost (one batched call) — fetches USD cost for all of them
          3. Sort by cost descending, keep top MAX_RESOURCES_PER_SCAN
          4. Build the compact payload that will be handed to the AI on its
             first list_resources call

        This keeps the AI context bounded regardless of account size:
          - 10K raw resources → ~3K after non-billable filter → top 200 by cost
          - The AI never sees zero-cost noise
        """
        logger.info("prefilter_start")

        resources = self._adapter.list_resources(ignore_regions=ignore_regions or None)
        total_discovered = len(resources)

        if not resources:
            self._prefiltered_payload = []
            logger.info("prefilter_complete", extra={"discovered": 0, "sent_to_ai": 0})
            return []

        # Batch cost fetch — one API call for all resource IDs
        resource_ids = [r.resource_id for r in resources]
        try:
            costs = self._adapter.get_cost(resource_ids=resource_ids)
        except Exception as exc:
            logger.warning("prefilter_cost_fetch_failed", extra={"error": str(exc)})
            costs = {}

        # Attach cost to each resource and sort descending
        resources_with_cost = [
            (r, costs.get(r.resource_id, 0.0))
            for r in resources
        ]
        resources_with_cost.sort(key=lambda x: x[1], reverse=True)

        # Cap at MAX_RESOURCES_PER_SCAN
        capped = resources_with_cost[:MAX_RESOURCES_PER_SCAN]
        dropped = total_discovered - len(capped)

        if dropped > 0:
            logger.info(
                "prefilter_capped",
                extra={
                    "discovered": total_discovered,
                    "sent_to_ai": len(capped),
                    "dropped_zero_cost": dropped,
                    "cap": MAX_RESOURCES_PER_SCAN,
                },
            )

        # Build compact payload — include cost so AI doesn't need to call get_cost
        # for the initial triage (it already has it)
        payload = []
        for resource, cost in capped:
            entry = _compress_resource(resource.to_dict())
            if cost > 0.0:
                entry["cost_usd"] = round(cost, 2)
            payload.append(entry)

        self._prefiltered_payload = payload

        logger.info(
            "prefilter_complete",
            extra={"discovered": total_discovered, "sent_to_ai": len(payload)},
        )
        return payload

    def _execute(self, tc: ToolCall) -> tuple[str, bool]:
        """Dispatch a tool call to the adapter. Returns (result_str, is_error)."""
        try:
            match tc.name:
                case "list_resources":
                    # Return the pre-filtered, cost-sorted list built in Phase 0.
                    # The adapter is NOT called again here — avoids a second full
                    # Resource Explorer / Asset Inventory scan mid-conversation.
                    return json.dumps(
                        self._prefiltered_payload,
                        default=str,
                        separators=(",", ":"),
                    ), False

                case "get_metrics":
                    summary = self._adapter.get_metrics(**tc.arguments)
                    return json.dumps(
                        summary.to_dict(), default=str, separators=(",", ":")
                    ), False

                case "get_cost":
                    costs = self._adapter.get_cost(**tc.arguments)
                    return json.dumps(costs, default=str, separators=(",", ":")), False

                case "get_last_activity":
                    activity = self._adapter.get_last_activity(**tc.arguments)
                    result = activity.isoformat() if activity else "null"
                    return result, False

                case _:
                    return f"Unknown tool: {tc.name!r}", True

        except Exception as exc:
            logger.error("tool_error", extra={"tool": tc.name, "error": str(exc)})
            return f"Tool error: {exc}", True


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _compress_resource(r: dict) -> dict:
    """
    Return a compact resource dict to minimise tokens sent to the AI.

    Strategy:
    - Shorten key names (resource_id → id, resource_type → type)
    - Truncate long ARNs to their short form for the list view.
      The full ARN is passed back by the AI when it calls get_metrics /
      get_cost / get_last_activity, so the adapter always receives the
      canonical identifier.
    - Drop None / empty values entirely
    - Keep tags only if non-empty (they carry owner/env signals)
    """
    resource_id = r["resource_id"]
    out: dict = {
        "id": resource_id,
        "type": r["resource_type"],
        "region": r["region"],
    }
    if r.get("name"):
        out["name"] = r["name"]
    if r.get("tags"):
        out["tags"] = r["tags"]
    # cloud field is redundant (the AI already knows the cloud from system prompt)
    return out


def _short_id(resource_id: str) -> str:
    """
    Return a short human-readable identifier from a full ARN or resource path.

    Examples:
      arn:aws:ec2:us-east-1:123:instance/i-0abc123  →  i-0abc123
      arn:aws:s3:::my-bucket                         →  my-bucket
      projects/my-proj/zones/us-central1-a/instances/vm-1  →  vm-1
      /subscriptions/xxx/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm  →  vm

    The full ID is still stored in the `id` field — this is only used in log
    messages and debugging. The AI always sends back the full `id` when calling
    adapter tools.
    """
    # Strip trailing slashes, take last path segment
    return resource_id.rstrip("/").rsplit("/", 1)[-1]


def _parse_findings(
    args: dict[str, Any],
    cloud: str,
) -> tuple[list[ResourceFinding], str]:
    """Convert the AI's submit_findings arguments into ResourceFinding objects."""
    scan_time = datetime.now(tz=timezone.utc)
    raw_findings: list[dict] = args.get("findings", [])
    executive_summary: str = args.get("executive_summary", "")

    findings = [
        ResourceFinding.from_dict({**f, "cloud": f.get("cloud", cloud)}, scan_time)
        for f in raw_findings
    ]

    # Ensure descending cost order regardless of what the AI returned
    findings.sort(key=lambda f: f.estimated_monthly_cost, reverse=True)

    return findings, executive_summary
