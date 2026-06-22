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
            except Exception as exc:  # noqa: BLE001
                logger.error("chat_ai_call_failed", error=str(exc))
                error_text = f"Sorry, I couldn't complete that request: {exc}"
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
        """Drop oldest messages when history exceeds the token budget."""
        total_chars = sum(self._estimate_message_chars(m) for m in self._messages)
        token_estimate = total_chars // _CHARS_PER_TOKEN

        if token_estimate <= TOKEN_BUDGET:
            return

        dropped = 0
        while len(self._messages) > 1 and token_estimate > TOKEN_BUDGET:
            removed = self._messages.pop(0)
            token_estimate -= self._estimate_message_chars(removed) // _CHARS_PER_TOKEN
            dropped += 1

        if dropped > 0:
            context_msg = Message(
                role="user",
                text=(
                    f"[Context: {dropped} earlier messages were trimmed. "
                    f"You are analyzing {self._cloud.upper()} infrastructure "
                    f"for cost optimization. Resources have been loaded.]"
                ),
            )
            self._messages.insert(0, context_msg)
            logger.info("chat_history_trimmed", dropped=dropped)

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
