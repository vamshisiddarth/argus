from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from adapters.base import CloudAdapter
from ai.base import AIProvider, Message, Tool
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
                error_text = (
                    f"Failed to parse the AI response: {exc}. Try rephrasing."
                )
                self._messages.append(Message(role="assistant", text=error_text))
                return ChatResponse(
                    text=error_text,
                    turn_input_tokens=turn_input,
                    turn_output_tokens=turn_output,
                    turn_cost_usd=self._estimate_turn_cost(turn_input, turn_output),
                )
            except RuntimeError as exc:
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

            tool_results = self._loop._execute_tool_calls(response.tool_calls)
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

    def _trim_history(self) -> None:
        """Drop oldest messages when history exceeds the token budget.

        Attempts to summarize dropped messages via a cheap LLM call.
        Falls back to a static context marker if summarization fails.
        """
        total_chars = sum(self._estimate_message_chars(m) for m in self._messages)
        token_estimate = total_chars // _CHARS_PER_TOKEN

        if token_estimate <= TOKEN_BUDGET:
            return

        dropped_messages: list[Message] = []
        while len(self._messages) > 1 and token_estimate > TOKEN_BUDGET:
            removed = self._messages.pop(0)
            token_estimate -= self._estimate_message_chars(removed) // _CHARS_PER_TOKEN
            dropped_messages.append(removed)

        if not dropped_messages:
            return

        summary_text = self._summarize_dropped(dropped_messages)
        context_msg = Message(role="user", text=f"[Context: {summary_text}]")
        self._messages.insert(0, context_msg)
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
