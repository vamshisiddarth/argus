"""
AI provider backed by Azure OpenAI (GPT-4o).

Authentication uses DefaultAzureCredential — run:
    az login

No API key needed when running on Azure Functions with a managed identity.

Environment variables:
    AZURE_OPENAI_ENDPOINT    Azure OpenAI resource endpoint (required)
                             e.g. https://my-resource.openai.azure.com/
    AZURE_OPENAI_DEPLOYMENT  Deployment name (default: gpt-4o)
    AZURE_OPENAI_API_VERSION API version (default: 2024-10-21)
    AZURE_OPENAI_API_KEY     Optional — use only for local dev without az login
"""

from __future__ import annotations

import json
import time
from typing import Any

import openai
import structlog

from ai.base import AIProvider, AIResponse, Message, Tool, ToolCall

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
_BASE_DELAY = 1.0


class AzureOpenAIProvider(AIProvider):
    """
    AI provider backed by Azure OpenAI GPT-4o.
    Uses DefaultAzureCredential (managed identity / az login) — no API key needed
    when running on Azure infrastructure.

    Falls back to AZURE_OPENAI_API_KEY for local dev without az login.
    """

    DEFAULT_DEPLOYMENT = "gpt-4o"
    DEFAULT_API_VERSION = "2024-10-21"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TEMPERATURE = 0.0

    def __init__(
        self,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        temperature: float | None = None,
    ) -> None:
        from core.config import get_settings

        cfg = get_settings().ai
        self._endpoint = endpoint or cfg.azure_openai_endpoint
        if not self._endpoint:
            raise EnvironmentError(
                "AZURE_OPENAI_ENDPOINT is not set. "
                "Set it in .env or pass endpoint= explicitly. "
                "Example: https://my-resource.openai.azure.com/"
            )
        self._deployment = deployment or cfg.resolved_model("azure_openai")
        self._api_version = api_version or cfg.azure_openai_api_version
        self._max_tokens = max_tokens
        self._temperature = temperature if temperature is not None else cfg.temperature

        resolved_key = api_key or cfg.azure_openai_api_key
        if resolved_key:
            self._client = openai.AzureOpenAI(
                azure_endpoint=self._endpoint,
                api_key=resolved_key,
                api_version=self._api_version,
            )
            self._credential = None
        else:
            # DefaultAzureCredential: works with managed identity, az login, env vars
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential,
                "https://cognitiveservices.azure.com/.default",
            )
            self._client = openai.AzureOpenAI(
                azure_endpoint=self._endpoint,
                azure_ad_token_provider=token_provider,
                api_version=self._api_version,
            )
            self._credential = credential

    @classmethod
    def from_env(cls) -> "AzureOpenAIProvider":
        return cls()

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        openai_messages = self._build_messages(messages, system_prompt)
        openai_tools = [self._to_openai_tool(t) for t in tools] if tools else None

        kwargs: dict[str, Any] = {
            "model": self._deployment,
            "messages": openai_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        response = self._call_with_retry(kwargs)
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_with_retry(self, kwargs: dict[str, Any]) -> Any:
        delay = _BASE_DELAY
        for attempt in range(MAX_RETRIES):
            try:
                return self._client.chat.completions.create(**kwargs)
            except openai.BadRequestError as exc:
                # Reasoning models (o1/o3/o4) have two restrictions vs standard models:
                #   1. Require max_completion_tokens instead of max_tokens.
                #   2. Do not accept temperature (fixed at 1).
                # Catch both in one retry so we don't need two round-trips.
                err_msg = str(exc)
                changed = False
                if "max_completion_tokens" in err_msg and "max_tokens" in kwargs:
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                    changed = True
                if "temperature" in err_msg and "temperature" in kwargs:
                    kwargs.pop("temperature")
                    changed = True
                if changed:
                    continue
                raise
            except openai.RateLimitError:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "Azure OpenAI rate limited (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise
            except openai.AuthenticationError as exc:
                raise EnvironmentError(
                    "Azure OpenAI authentication failed. "
                    "Run 'az login' or set AZURE_OPENAI_API_KEY."
                ) from exc
        raise RuntimeError("Unreachable")  # pragma: no cover

    def _build_messages(
        self,
        messages: list[Message],
        system_prompt: str | None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        if system_prompt:
            result.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.role == "user":
                if msg.tool_results:
                    for tr in msg.tool_results:
                        result.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr.tool_call_id,
                                "content": tr.content,
                            }
                        )
                else:
                    result.append({"role": "user", "content": msg.text or ""})

            else:
                # assistant
                tool_calls_out = []
                for tc in msg.tool_calls:
                    tool_calls_out.append(
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                    )
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.text or "",
                }
                if tool_calls_out:
                    assistant_msg["tool_calls"] = tool_calls_out
                result.append(assistant_msg)

        return result

    def _to_openai_tool(self, tool: Tool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    def _parse_response(self, response: Any) -> AIResponse:
        choice = response.choices[0]
        message = choice.message
        stop_reason = choice.finish_reason  # "stop" | "tool_calls" | "length"

        text: str | None = message.content or None
        tool_calls: list[ToolCall] = []

        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        # Normalise to internal vocabulary
        if tool_calls:
            stop_reason = "tool_use"
        elif stop_reason == "stop":
            stop_reason = "end_turn"
        elif stop_reason == "length":
            stop_reason = "max_tokens"

        usage = getattr(response, "usage", None)
        return AIResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        )
