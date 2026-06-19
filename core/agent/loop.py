from __future__ import annotations

import json
import os as _os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import structlog

from adapters.base import CloudAdapter
from ai.base import AIProvider, Message, Tool, ToolCall, ToolResult
from core.agent.prompts import build_system_prompt, build_tool_schemas
from core.models.finding import ResourceFinding

logger = structlog.get_logger(__name__)

MAX_ITERATIONS = 50

# Override via MAX_RESOURCES_PER_SCAN env var for large accounts.
MAX_RESOURCES_PER_SCAN: int = int(_os.environ.get("MAX_RESOURCES_PER_SCAN", "200"))

ADAPTER_CONCURRENCY: int = int(_os.environ.get("ADAPTER_CONCURRENCY", "10"))

_PARALLELIZABLE_TOOLS = frozenset({"get_metrics", "get_last_activity"})


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
        system_prompt = build_system_prompt(
            cloud=cloud, ignore_regions=ignore_regions, accounts=accounts
        )

        # ------------------------------------------------------------------
        # Phase 0 — pre-filter (outside AI context, no tokens consumed)
        # Fetch all resources + batch cost, then hand only the top-N by cost
        # to the agent. This keeps context small regardless of account size.
        # ------------------------------------------------------------------
        self._prefilter_resources(ignore_regions)

        self.total_input_tokens = 0
        self.total_output_tokens = 0

        messages: list[Message] = [
            Message(role="user", text="Begin your cloud cost analysis now.")
        ]

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info("agent_iteration", iteration=iteration)

            response = self._ai.chat(messages, self._tools, system_prompt=system_prompt)
            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            if response.stop_reason == "tool_use":
                # Check first — submit_findings terminates the loop immediately
                for tc in response.tool_calls:
                    if tc.name == "submit_findings":
                        logger.info(
                            "agent_complete",
                            findings_count=len(tc.arguments.get("findings", [])),
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

                # Parallel for metrics/activity, sequential for the rest
                tool_results = self._execute_tool_calls(response.tool_calls)

                messages.append(Message(role="user", tool_results=tool_results))

            else:
                # end_turn or max_tokens without submit_findings — shouldn't happen
                # if the prompt is working, but handle gracefully
                logger.warning(
                    "agent_stopped_without_findings",
                    stop_reason=response.stop_reason,
                )
                return [], response.text or ""

        raise RuntimeError(
            f"Agent loop exceeded {MAX_ITERATIONS} iterations "
            "without submitting findings. "
            "Check the system prompt or increase MAX_ITERATIONS."
        )

    def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        parallel = [tc for tc in tool_calls if tc.name in _PARALLELIZABLE_TOOLS]
        sequential = [tc for tc in tool_calls if tc.name not in _PARALLELIZABLE_TOOLS]

        results_by_id: dict[str, ToolResult] = {}

        for tc in sequential:
            content, is_error = self._execute(tc)
            logger.info("tool_executed", tool=tc.name, is_error=is_error)
            results_by_id[tc.id] = ToolResult(
                tool_call_id=tc.id, content=content, is_error=is_error
            )

        if parallel:
            results_by_id.update(self._execute_parallel(parallel))

        return [results_by_id[tc.id] for tc in tool_calls]

    def _execute_parallel(self, tool_calls: list[ToolCall]) -> dict[str, ToolResult]:
        results: dict[str, ToolResult] = {}
        max_workers = min(ADAPTER_CONCURRENCY, len(tool_calls))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_tc = {executor.submit(self._execute, tc): tc for tc in tool_calls}
            for future in as_completed(future_to_tc):
                tc = future_to_tc[future]
                content, is_error = future.result()
                logger.info(
                    "tool_executed", tool=tc.name, is_error=is_error, parallel=True
                )
                results[tc.id] = ToolResult(
                    tool_call_id=tc.id, content=content, is_error=is_error
                )

        return results

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
        resources = _apply_exclusion_filters(resources)
        total_discovered = len(resources)

        if not resources:
            self._prefiltered_payload = []
            logger.info("prefilter_complete", discovered=0, sent_to_ai=0)
            return []

        # Batch cost fetch — one API call for all resource IDs
        resource_ids = [r.resource_id for r in resources]
        try:
            costs = self._adapter.get_cost(resource_ids=resource_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("prefilter_cost_fetch_failed", error=str(exc))
            costs = {}

        # Attach cost to each resource and sort descending
        resources_with_cost = [(r, costs.get(r.resource_id, 0.0)) for r in resources]
        resources_with_cost.sort(key=lambda x: x[1], reverse=True)

        # Cap at MAX_RESOURCES_PER_SCAN
        capped = resources_with_cost[:MAX_RESOURCES_PER_SCAN]
        dropped = total_discovered - len(capped)

        if dropped > 0:
            logger.info(
                "prefilter_capped",
                discovered=total_discovered,
                sent_to_ai=len(capped),
                dropped_zero_cost=dropped,
                cap=MAX_RESOURCES_PER_SCAN,
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
            discovered=total_discovered,
            sent_to_ai=len(payload),
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
                    return (
                        json.dumps(
                            self._prefiltered_payload,
                            default=str,
                            separators=(",", ":"),
                        ),
                        False,
                    )

                case "get_metrics":
                    summary = self._adapter.get_metrics(**tc.arguments)
                    return (
                        json.dumps(
                            summary.to_dict(), default=str, separators=(",", ":")
                        ),
                        False,
                    )

                case "get_cost":
                    costs = self._adapter.get_cost(**tc.arguments)
                    return json.dumps(costs, default=str, separators=(",", ":")), False

                case "get_last_activity":
                    activity = self._adapter.get_last_activity(**tc.arguments)
                    result = activity.isoformat() if activity else "null"
                    return result, False

                case _:
                    return f"Unknown tool: {tc.name!r}", True

        except Exception as exc:  # noqa: BLE001
            logger.error("tool_error", tool=tc.name, error=str(exc))
            return f"Tool error: {exc}", True


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _apply_exclusion_filters(resources: list[Any]) -> list[Any]:
    exclude_tags = _parse_exclude_tags()
    exclude_types = _parse_exclude_types()

    if not exclude_tags and not exclude_types:
        return resources

    filtered = []
    excluded_count = 0
    for r in resources:
        if exclude_types and r.resource_type in exclude_types:
            excluded_count += 1
            continue
        if exclude_tags and _tags_match(r.tags, exclude_tags):
            excluded_count += 1
            continue
        filtered.append(r)

    if excluded_count > 0:
        logger.info(
            "exclusion_filter_applied",
            excluded=excluded_count,
            remaining=len(filtered),
        )
    return filtered


def _parse_exclude_tags() -> dict[str, str]:
    raw = _os.environ.get("EXCLUDE_TAGS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except (json.JSONDecodeError, TypeError):
        logger.warning("exclude_tags_invalid_json", raw=raw)
    return {}


def _parse_exclude_types() -> set[str]:
    raw = _os.environ.get("EXCLUDE_RESOURCE_TYPES", "").strip()
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def _tags_match(resource_tags: dict[str, str], exclude_tags: dict[str, str]) -> bool:
    for key, value in exclude_tags.items():
        if resource_tags.get(key) == value:
            return True
    return False


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
