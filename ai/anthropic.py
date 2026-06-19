from __future__ import annotations

import random
import time
from typing import Any

import anthropic as anthropic_sdk
import structlog

from ai.base import AIProvider, AIResponse, Message, Tool, ToolCall

logger = structlog.get_logger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0


class AnthropicProvider(AIProvider):
    """
    AI provider backed by the Anthropic direct API.
    Works on any cloud — no AWS/GCP/Azure auth needed.
    Best for local development and contributors without cloud AI access.
    Configure via ANTHROPIC_API_KEY and optionally ANTHROPIC_MODEL env vars.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TEMPERATURE = 0.0

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
    ) -> None:
        from core.config import get_settings

        cfg = get_settings().ai
        resolved_key = api_key or cfg.anthropic_api_key
        if not resolved_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it or pass api_key= explicitly."
            )
        self._client = anthropic_sdk.Anthropic(api_key=resolved_key, timeout=60.0)
        self._model = model or cfg.resolved_model("anthropic")
        self._max_tokens = max_tokens
        self._temperature = temperature if temperature is not None else cfg.temperature

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": [self._to_anthropic_message(m) for m in messages],
            "tools": [self._to_anthropic_tool(t) for t in tools],
        }
        if system_prompt:
            # cache_control pins the system prompt in Anthropic's prompt cache.
            # After the first iteration it's served from cache — no reprocessing charge.
            # Requires claude-3-5-* or claude-sonnet-4-* models.
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        response = self._call_with_retry(kwargs)
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    def _call_with_retry(self, kwargs: dict[str, Any]) -> Any:
        delay = _BASE_DELAY
        for attempt in range(_MAX_RETRIES):
            try:
                return self._client.messages.create(**kwargs)
            except (
                anthropic_sdk.RateLimitError,
                anthropic_sdk.InternalServerError,
            ) as exc:
                if attempt < _MAX_RETRIES - 1:
                    jitter = random.uniform(0, delay * 0.5)  # noqa: S311
                    sleep_time = delay + jitter
                    logger.warning(
                        "anthropic_api_retrying",
                        error_type=type(exc).__name__,
                        attempt=attempt + 1,
                        max_retries=_MAX_RETRIES,
                        retry_in=round(sleep_time, 1),
                    )
                    time.sleep(sleep_time)
                    delay *= 2
                else:
                    raise
        raise RuntimeError("Unreachable")  # pragma: no cover

    # ------------------------------------------------------------------
    # Internal conversion helpers
    # ------------------------------------------------------------------

    def _to_anthropic_message(self, msg: Message) -> dict[str, Any]:
        if msg.role == "user":
            if msg.tool_results:
                return {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tr.tool_call_id,
                            "content": tr.content,
                            **({"is_error": True} if tr.is_error else {}),
                        }
                        for tr in msg.tool_results
                    ],
                }
            return {"role": "user", "content": msg.text or ""}

        # assistant
        content: list[dict[str, Any]] = []
        if msg.text:
            content.append({"type": "text", "text": msg.text})
        for tc in msg.tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
            )
        return {"role": "assistant", "content": content}

    def _to_anthropic_tool(self, tool: Tool) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    def _parse_response(self, response: Any) -> AIResponse:
        tool_calls: list[ToolCall] = []
        text: str | None = None

        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input),
                    )
                )
            elif block.type == "text":
                text = block.text

        usage = getattr(response, "usage", None)
        return AIResponse(
            stop_reason=response.stop_reason,
            text=text,
            tool_calls=tool_calls,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )
