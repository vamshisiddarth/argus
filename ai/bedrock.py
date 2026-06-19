from __future__ import annotations

import os
import time
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

from ai.base import AIProvider, AIResponse, Message, Tool, ToolCall

logger = structlog.get_logger(__name__)

MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds; doubles each retry


class BedrockProvider(AIProvider):
    """
    AI provider backed by Amazon Bedrock Converse API.
    Uses the execution role when running inside Lambda — no API keys needed.
    Configure via BEDROCK_MODEL_ID and BEDROCK_REGION env vars.
    """

    DEFAULT_MODEL = "anthropic.claude-sonnet-4-6"
    DEFAULT_REGION = "us-east-1"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_TEMPERATURE = 0.0

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
        session: Any = None,
    ) -> None:
        self._model_id = model_id or os.environ.get(
            "AI_MODEL", os.environ.get("BEDROCK_MODEL_ID", self.DEFAULT_MODEL)
        )
        resolved_region = region or os.environ.get(
            "BEDROCK_REGION", self.DEFAULT_REGION
        )
        self._max_tokens = max_tokens
        self._temperature = (
            temperature
            if temperature is not None
            else float(os.environ.get("AI_TEMPERATURE", str(self.DEFAULT_TEMPERATURE)))
        )

        boto_session = session or boto3.Session(region_name=resolved_region)
        self._client = boto_session.client(
            "bedrock-runtime", region_name=resolved_region
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        kwargs: dict[str, Any] = {
            "modelId": self._model_id,
            "messages": [self._to_bedrock_message(m) for m in messages],
            "inferenceConfig": {
                "maxTokens": self._max_tokens,
                "temperature": self._temperature,
            },
        }
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]
        if tools:
            kwargs["toolConfig"] = {"tools": [self._to_bedrock_tool(t) for t in tools]}

        response = self._call_with_retry(kwargs)
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_with_retry(self, kwargs: dict[str, Any]) -> Any:
        delay = _BASE_DELAY
        for attempt in range(MAX_RETRIES):
            try:
                return self._client.converse(**kwargs)
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "ThrottlingException" and attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "Bedrock throttled (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise
        raise RuntimeError("Unreachable")  # pragma: no cover

    def _to_bedrock_message(self, msg: Message) -> dict[str, Any]:
        if msg.role == "user":
            if msg.tool_results:
                return {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": tr.tool_call_id,
                                "content": [{"text": tr.content}],
                                **({"status": "error"} if tr.is_error else {}),
                            }
                        }
                        for tr in msg.tool_results
                    ],
                }
            return {"role": "user", "content": [{"text": msg.text or ""}]}

        # assistant
        content: list[dict[str, Any]] = []
        if msg.text:
            content.append({"text": msg.text})
        for tc in msg.tool_calls:
            content.append(
                {
                    "toolUse": {
                        "toolUseId": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                }
            )
        return {"role": "assistant", "content": content}

    def _to_bedrock_tool(self, tool: Tool) -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {"json": tool.input_schema},
            }
        }

    def _parse_response(self, response: dict[str, Any]) -> AIResponse:
        content_blocks: list[dict[str, Any]] = (
            response.get("output", {}).get("message", {}).get("content", [])
        )
        stop_reason: str = response.get("stopReason", "end_turn")

        tool_calls: list[ToolCall] = []
        text: str | None = None

        for block in content_blocks:
            if "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(
                    ToolCall(
                        id=tu["toolUseId"],
                        name=tu["name"],
                        arguments=dict(tu.get("input", {})),
                    )
                )
            elif "text" in block:
                text = block["text"]

        usage = response.get("usage", {})
        return AIResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        )
