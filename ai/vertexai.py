"""
AI provider backed by Google Vertex AI (Gemini models).

Authentication uses Application Default Credentials (ADC) — run:
    gcloud auth application-default login

No API key needed when running on Cloud Run / GCE with the right service account.

Environment variables:
    VERTEXAI_PROJECT   GCP project ID (required)
    VERTEXAI_LOCATION  GCP region (default: us-central1)
    VERTEXAI_MODEL     Model name (default: gemini-1.5-pro-002)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import google.auth
import google.auth.transport.requests
import openai

from ai.base import AIProvider, AIResponse, Message, Tool, ToolCall

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
_BASE_DELAY = 1.0


class VertexAIProvider(AIProvider):
    """
    AI provider backed by Vertex AI Gemini models.
    Uses the google-cloud-aiplatform SDK — included via the openai compat layer
    or directly via vertexai package. Falls back to the OpenAI-compatible
    Vertex AI endpoint so we can reuse the openai SDK already in requirements.txt.

    Model: gemini-1.5-pro-002 (default) — supports function calling + large context.
    """

    DEFAULT_MODEL = "gemini-1.5-pro-002"
    DEFAULT_LOCATION = "us-central1"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        project: str | None = None,
        location: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._project = project or os.environ.get("VERTEXAI_PROJECT")
        if not self._project:
            raise EnvironmentError(
                "VERTEXAI_PROJECT is not set. "
                "Set it in .env or pass project= explicitly."
            )
        self._location = location or os.environ.get(
            "VERTEXAI_LOCATION", self.DEFAULT_LOCATION
        )
        self._model = model or os.environ.get("VERTEXAI_MODEL", self.DEFAULT_MODEL)
        self._max_tokens = max_tokens

        # Use openai SDK with the Vertex AI endpoint.
        # This avoids adding google-cloud-aiplatform as a dependency.
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())

        self._client = openai.OpenAI(
            base_url=(
                f"https://{self._location}-aiplatform.googleapis.com/v1beta1/"
                f"projects/{self._project}/locations/{self._location}/endpoints/openapi"
            ),
            api_key=credentials.token,
        )
        self._credentials = credentials

    @classmethod
    def from_env(cls) -> "VertexAIProvider":
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
            "model": self._model,
            "messages": openai_messages,
            "max_tokens": self._max_tokens,
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
                # Refresh credentials if they may have expired (1-hour TTL)
                if not self._credentials.valid:
                    self._credentials.refresh(google.auth.transport.requests.Request())
                    self._client.api_key = self._credentials.token

                return self._client.chat.completions.create(**kwargs)
            except openai.RateLimitError:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "Vertex AI rate limited (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise
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
                    # Each tool result is its own message in the OpenAI protocol
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
                # assistant — may have text, tool_calls, or both
                content: list[dict[str, Any]] | str = msg.text or ""
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
                    "content": content,
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

        # Normalise finish_reason to our internal vocabulary
        if tool_calls:
            stop_reason = "tool_use"
        elif stop_reason == "stop":
            stop_reason = "end_turn"
        elif stop_reason == "length":
            stop_reason = "max_tokens"

        return AIResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
        )
