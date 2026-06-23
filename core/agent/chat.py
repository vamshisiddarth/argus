from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog

from adapters.base import CloudAdapter
from ai.base import AIProvider, Message, Tool, ToolResult
from core.agent.loop import AgentLoop
from core.agent.prompts import build_chat_system_prompt, build_chat_tool_schemas
from core.token_tracker import BudgetExceededError, TokenTracker

logger = structlog.get_logger(__name__)

MAX_TOOL_ROUNDS = 8
TOKEN_BUDGET = 80_000
_CHARS_PER_TOKEN = 4

_SUMMARY_PROMPT = (
    "Summarize the key facts from this conversation so far in 2-3 sentences. "
    "Focus on: which resources were discussed, what was found (idle/active/costs), "
    "and any conclusions reached. Be specific — include resource IDs and numbers."
)


@dataclass
class ChatResponse:
    """Result of a single chat turn, including per-turn token usage."""

    text: str
    turn_input_tokens: int
    turn_output_tokens: int
    turn_cost_usd: float


class ChatSession:
    """Interactive conversation engine that reuses AgentLoop for tool dispatch."""

    def __init__(
        self,
        ai_provider: AIProvider,
        cloud_adapter: CloudAdapter,
        cloud: str,
        accounts: list[dict[str, Any]],
        ignore_regions: list[str] | None = None,
        budget_usd: float = 1.0,
        max_history_turns: int = 20,
        on_tool_call: Callable[[str, str], None] | None = None,
    ) -> None:
        self._ai = ai_provider
        self._cloud = cloud
        self._accounts = accounts
        self._ignore_regions = ignore_regions or []
        self._max_history_turns = max_history_turns
        self._on_tool_call = on_tool_call

        self._loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=cloud_adapter)
        self._tools: list[Tool] = [
            Tool(
                name=t["name"],
                description=t["description"],
                input_schema=t["input_schema"],
            )
            for t in build_chat_tool_schemas()
        ]

        self.tracker = TokenTracker(budget_usd=budget_usd, provider="anthropic")
        self._messages: list[Message] = []
        self._resources_loaded = False

    @property
    def is_resources_loaded(self) -> bool:
        return self._resources_loaded

    @property
    def cost_summary(self) -> dict[str, float | int]:
        return self.tracker.summary()

    def clear_history(self) -> None:
        self._messages.clear()
        self._resources_loaded = False

    def load_resources(self) -> None:
        """Prefetch resources via the adapter. Called lazily on first ask()."""
        if self._resources_loaded:
            return
        self._loop._prefilter_resources(self._ignore_regions)
        self._resources_loaded = True

    def ask(self, user_input: str) -> ChatResponse:
        """Process one user question. Handles multi-step tool calls internally."""
        if not self._resources_loaded:
            self.load_resources()

        self._messages.append(Message(role="user", text=user_input))
        self._trim_history()

        system_prompt = build_chat_system_prompt(
            cloud=self._cloud,
            ignore_regions=self._ignore_regions,
            accounts=self._accounts,
            has_cached_resources=self._resources_loaded,
        )

        turn_input = 0
        turn_output = 0

        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = self._ai.chat(
                    self._messages, self._tools, system_prompt=system_prompt
                )
            except (ConnectionError, TimeoutError, OSError) as exc:
                logger.warning("chat_network_error", error=str(exc))
                error_text = (
                    "Network error — couldn't reach the AI provider. "
                    "Check your connection and try again."
                )
                self._messages.append(Message(role="assistant", text=error_text))
                return ChatResponse(
                    text=error_text,
                    turn_input_tokens=turn_input,
                    turn_output_tokens=turn_output,
                    turn_cost_usd=self._estimate_turn_cost(turn_input, turn_output),
                )
            except (ValueError, TypeError, KeyError) as exc:
                logger.error("chat_response_parse_error", error=str(exc))
                error_text = f"Failed to parse the AI response: {exc}. Try rephrasing."
                self._messages.append(Message(role="assistant", text=error_text))
                return ChatResponse(
                    text=error_text,
                    turn_input_tokens=turn_input,
                    turn_output_tokens=turn_output,
                    turn_cost_usd=self._estimate_turn_cost(turn_input, turn_output),
                )
            except RuntimeError as exc:
                exc_str = str(exc).lower()
                if any(k in exc_str for k in ("rate", "throttl", "429", "too many")):
                    logger.warning("chat_rate_limited", error=str(exc))
                    error_text = "Rate limit hit — please wait a moment and try again."
                elif any(k in exc_str for k in ("credential", "auth", "token", "401")):
                    logger.error("chat_auth_error", error=str(exc))
                    error_text = f"Authentication error: {exc}. Check your credentials."
                else:
                    logger.error("chat_ai_provider_error", error=str(exc))
                    error_text = f"AI provider error: {exc}"
                self._messages.append(Message(role="assistant", text=error_text))
                return ChatResponse(
                    text=error_text,
                    turn_input_tokens=turn_input,
                    turn_output_tokens=turn_output,
                    turn_cost_usd=self._estimate_turn_cost(turn_input, turn_output),
                )

            turn_input += response.input_tokens
            turn_output += response.output_tokens

            try:
                self.tracker.record(response.input_tokens, response.output_tokens)
            except BudgetExceededError:
                budget_msg = (
                    f"Session budget of ${self.tracker.budget_usd:.2f} exceeded "
                    f"(${self.tracker.estimated_cost_usd:.4f} spent). "
                    f"Start a new session or increase --llm-budget."
                )
                self._messages.append(Message(role="assistant", text=budget_msg))
                return ChatResponse(
                    text=budget_msg,
                    turn_input_tokens=turn_input,
                    turn_output_tokens=turn_output,
                    turn_cost_usd=self._estimate_turn_cost(turn_input, turn_output),
                )

            if response.stop_reason != "tool_use":
                text = response.text or ""
                self._messages.append(Message(role="assistant", text=text))
                return ChatResponse(
                    text=text,
                    turn_input_tokens=turn_input,
                    turn_output_tokens=turn_output,
                    turn_cost_usd=self._estimate_turn_cost(turn_input, turn_output),
                )

            self._messages.append(
                Message(
                    role="assistant",
                    text=response.text,
                    tool_calls=response.tool_calls,
                )
            )

            for tc in response.tool_calls:
                if self._on_tool_call:
                    resource_id = tc.arguments.get(
                        "resource_id",
                        tc.arguments.get("resource_ids", [""])[0]
                        if isinstance(tc.arguments.get("resource_ids"), list)
                        else "",
                    )
                    self._on_tool_call(tc.name, resource_id)

            raw_results = self._loop._execute_tool_calls(response.tool_calls)
            # Map tool_call_id → tool name for formatting
            name_by_id = {tc.id: tc.name for tc in response.tool_calls}
            tool_results = [
                ToolResult(
                    tool_call_id=tr.tool_call_id,
                    content=ChatSession.format_tool_result(
                        name_by_id.get(tr.tool_call_id, "unknown"), tr.content
                    ),
                    is_error=tr.is_error,
                )
                for tr in raw_results
            ]
            self._messages.append(Message(role="user", tool_results=tool_results))

        safety_msg = (
            "I've used too many tool calls for this question. "
            "Try asking something more specific."
        )
        self._messages.append(Message(role="assistant", text=safety_msg))
        return ChatResponse(
            text=safety_msg,
            turn_input_tokens=turn_input,
            turn_output_tokens=turn_output,
            turn_cost_usd=self._estimate_turn_cost(turn_input, turn_output),
        )

    def force_summarize(self) -> None:
        """Summarize and compact history unconditionally, regardless of token budget."""
        if len(self._messages) < 4:
            return
        keep = self._messages[-4:]
        dropped = self._messages[:-4]
        summary = self._summarize_dropped(dropped)
        self._messages = [Message(role="user", text=f"[Context: {summary}]")] + keep
        logger.info("chat_force_summarized", dropped=len(dropped))

    @staticmethod
    def format_tool_result(tool_name: str, raw_content: str) -> str:
        """Convert raw JSON tool output to a compact human-readable summary.

        Returns raw_content unchanged if parsing fails — never raises.
        """
        try:
            return _format_dispatch(tool_name, raw_content)
        except Exception:  # noqa: BLE001
            return raw_content

    def _trim_history(self) -> None:
        """Drop oldest turns when history exceeds the token budget.

        Always drops complete turns (user + assistant + tool results) to avoid
        orphaning tool-call/tool-result pairs. Summarizes dropped messages via a
        cheap AI call; falls back to a static marker on failure.
        """
        total_chars = sum(self._estimate_message_chars(m) for m in self._messages)
        if total_chars // _CHARS_PER_TOKEN <= TOKEN_BUDGET:
            return

        turns = _group_into_turns(self._messages)
        dropped_messages: list[Message] = []

        while len(turns) > 1:
            chars = sum(self._estimate_message_chars(m) for turn in turns for m in turn)
            if chars // _CHARS_PER_TOKEN <= TOKEN_BUDGET:
                break
            dropped_messages.extend(turns.pop(0))

        if not dropped_messages:
            return

        self._messages = [m for turn in turns for m in turn]
        summary_text = self._summarize_dropped(dropped_messages)
        self._messages.insert(
            0, Message(role="user", text=f"[Context: {summary_text}]")
        )
        logger.info(
            "chat_history_trimmed",
            dropped=len(dropped_messages),
            summarized=summary_text[:80],
        )

    def _summarize_dropped(self, dropped: list[Message]) -> str:
        """Ask the AI to summarize dropped messages. Falls back to static text."""
        conversation_text = []
        for msg in dropped:
            if msg.text:
                label = "User" if msg.role == "user" else "Assistant"
                conversation_text.append(f"{label}: {msg.text}")
            for tc in msg.tool_calls:
                conversation_text.append(
                    f"Tool call: {tc.name}({json.dumps(tc.arguments, default=str)})"
                )
            for tr in msg.tool_results:
                snippet = (
                    tr.content[:200] + "..." if len(tr.content) > 200 else tr.content
                )
                conversation_text.append(f"Tool result: {snippet}")

        if not conversation_text:
            return self._static_context_summary(len(dropped))

        summary_input = "\n".join(conversation_text[-30:])

        try:
            summary_messages = [
                Message(role="user", text=f"{_SUMMARY_PROMPT}\n\n{summary_input}")
            ]
            response = self._ai.chat(summary_messages, tools=[], system_prompt=None)
            self.tracker.record(response.input_tokens, response.output_tokens)

            if response.text and len(response.text) > 10:
                return response.text
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError):
            logger.debug("chat_summary_failed_falling_back_to_static")

        return self._static_context_summary(len(dropped))

    def _static_context_summary(self, dropped_count: int) -> str:
        return (
            f"{dropped_count} earlier messages were trimmed. "
            f"You are analyzing {self._cloud.upper()} infrastructure "
            f"for cost optimization. Resources have been loaded."
        )

    @staticmethod
    def _estimate_message_chars(msg: Message) -> int:
        size = len(msg.text or "")
        for tc in msg.tool_calls:
            size += len(json.dumps(tc.arguments, default=str))
        for tr in msg.tool_results:
            size += len(tr.content)
        return size

    def _estimate_turn_cost(self, input_tokens: int, output_tokens: int) -> float:
        from core.token_tracker import _DEFAULT_PRICING, _PRICING

        input_rate, output_rate = _PRICING.get(self.tracker.provider, _DEFAULT_PRICING)
        return round(
            (input_tokens / 1_000_000 * input_rate)
            + (output_tokens / 1_000_000 * output_rate),
            4,
        )


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------


def _group_into_turns(messages: list[Message]) -> list[list[Message]]:
    """Group a flat message list into logical turns.

    A turn is: one user message, followed by one assistant message (which may
    carry tool_calls), followed by zero or more user messages that are
    tool-result-only responses. Grouping ensures _trim_history never splits
    a tool-call / tool-result pair.
    """
    turns: list[list[Message]] = []
    current: list[Message] = []

    for msg in messages:
        if msg.role == "user" and not msg.tool_results and current:
            # New human turn starts — flush the current group
            turns.append(current)
            current = [msg]
        else:
            current.append(msg)

    if current:
        turns.append(current)

    return turns


# ---------------------------------------------------------------------------
# Tool result formatters
# ---------------------------------------------------------------------------


def _format_dispatch(tool_name: str, raw_content: str) -> str:
    match tool_name:
        case "list_resources":
            return _fmt_list_resources(raw_content)
        case "get_metrics":
            return _fmt_get_metrics(raw_content)
        case "get_cost":
            return _fmt_get_cost(raw_content)
        case "get_last_activity":
            return _fmt_get_last_activity(raw_content)
        case _:
            return raw_content


def _fmt_list_resources(raw: str) -> str:
    resources: list[dict] = json.loads(raw)
    if not resources:
        return "No resources found."

    # Count by type
    type_counts: dict[str, int] = {}
    regions: set[str] = set()
    for r in resources:
        rtype = r.get("type", "unknown")
        type_counts[rtype] = type_counts.get(rtype, 0) + 1
        if r.get("region"):
            regions.add(r["region"])

    # Build type summary — show top 3 types, group rest as "other"
    sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
    top_types = sorted_types[:3]
    other_count = sum(c for _, c in sorted_types[3:])
    type_parts = [f"{c} {t}" for t, c in top_types]
    if other_count:
        type_parts.append(f"{other_count} other")

    region_str = ", ".join(sorted(regions)) if regions else "unknown region"
    header = (
        f"Found {len(resources)} resources across {region_str} "
        f"({', '.join(type_parts)})."
    )

    # Top 5 by cost_usd
    with_cost = sorted(resources, key=lambda r: r.get("cost_usd", 0.0), reverse=True)
    top5 = with_cost[:5]
    lines = [header, "Top 5 by estimated monthly cost:"]
    for r in top5:
        rid = r.get("id", "?")
        rtype = r.get("type", "?")
        region = r.get("region", "?")
        cost = r.get("cost_usd", 0.0)
        name = r.get("name", "")
        label = f"{rid}" + (f" ({name})" if name else "")
        lines.append(f"  • {label} [{rtype}, {region}] — ${cost:.2f}/mo")

    n = len(resources)
    lines.append(f"Full inventory ({n} resources) available for follow-up questions.")
    return "\n".join(lines)


def _fmt_get_metrics(raw: str) -> str:
    data: dict = json.loads(raw)
    metrics: dict = data.get("metrics", {})
    window_days: int = data.get("window_days", 14)

    if not metrics:
        return (
            f"No metric data available for this resource "
            f"in the {window_days}-day lookback window."
        )

    lines = [f"Metrics ({window_days}-day window):"]
    last_point: str | None = data.get("last_datapoint")

    # Pick the most informative metrics — prefer CPU, network, request counts
    _PRIORITY = [
        "CPUUtilization",
        "cpu",
        "NetworkIn",
        "NetworkOut",
        "RequestCount",
        "Invocations",
        "DatabaseConnections",
        "ReadIOPS",
        "WriteIOPS",
    ]
    ordered = sorted(
        metrics.items(),
        key=lambda kv: _PRIORITY.index(kv[0]) if kv[0] in _PRIORITY else len(_PRIORITY),
    )

    shown = 0
    for metric_name, stats in ordered:
        if shown >= 5:
            break
        if not isinstance(stats, dict):
            continue
        avg = stats.get("avg")
        maximum = stats.get("max")
        parts = []
        if avg is not None:
            parts.append(f"avg {avg:g}")
        if maximum is not None:
            parts.append(f"max {maximum:g}")
        if parts:
            lines.append(f"  • {metric_name}: {', '.join(parts)}")
            shown += 1

    if last_point:
        lines.append(f"Last datapoint: {last_point[:10]}.")

    # Heuristic idle signal based on CPU avg
    cpu_stats = metrics.get("CPUUtilization") or metrics.get("cpu")
    if isinstance(cpu_stats, dict):
        avg_cpu = cpu_stats.get("avg", 0)
        if avg_cpu is not None and avg_cpu < 5:
            lines.append("Signal: consistently idle (CPU < 5% average).")

    return "\n".join(lines)


def _fmt_get_cost(raw: str) -> str:
    costs: dict[str, float] = json.loads(raw)
    if not costs:
        return "No cost data returned."

    total = sum(costs.values())
    sorted_items = sorted(costs.items(), key=lambda x: x[1], reverse=True)

    lines = ["Cost data (30 days):", f"Total: ${total:.2f}"]
    zero_count = 0
    for rid, amount in sorted_items:
        if amount == 0.0:
            zero_count += 1
            continue
        lines.append(f"  • {rid}: ${amount:.2f}")
    if zero_count:
        lines.append(f"  • ({zero_count} resource(s) at $0.00 — no cost data recorded)")
    return "\n".join(lines)


def _fmt_get_last_activity(raw: str) -> str:
    raw = raw.strip().strip('"')
    if raw in ("null", "", "None"):
        return (
            "Last activity: no record in the lookback window "
            "(resource may be fully idle)."
        )
    try:
        dt = datetime.fromisoformat(raw)
        now = datetime.now(tz=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days_ago = (now - dt).days
        date_str = dt.strftime("%Y-%m-%d")
        return f"Last activity: {date_str} ({days_ago} days ago)."
    except ValueError:
        return f"Last activity: {raw}"
