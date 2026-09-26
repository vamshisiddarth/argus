# Adding an AI Provider

This guide walks through adding support for a new AI model or provider.

## 1. Create the provider file

```python title="ai/myprovider.py"
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from ai.base import AIProvider, AIResponse, Message, Tool, ToolCall

logger = logging.getLogger(__name__)
MAX_RETRIES = 3


class MyProvider(AIProvider):
    """
    AI provider backed by MyModel API.
    """

    DEFAULT_MODEL = "my-model-v1"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        resolved_key = api_key or os.environ.get("MYPROVIDER_API_KEY")
        if not resolved_key:
            raise EnvironmentError("MYPROVIDER_API_KEY is not set.")
        self._model = model or self.DEFAULT_MODEL
        self._max_tokens = max_tokens
        # Initialize your SDK client here

    @classmethod
    def from_env(cls) -> "MyProvider":
        return cls()

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        # 1. Convert messages to your provider's format
        # 2. Call the API
        # 3. Parse the response back to AIResponse
        ...
```

## 2. Message conversion

The `Message` type has three shapes. Handle all three:

```python
def _to_provider_messages(self, messages: list[Message], system_prompt: str | None) -> list[dict]:
    result = []

    if system_prompt:
        result.append({"role": "system", "content": system_prompt})

    for msg in messages:
        if msg.role == "user" and msg.tool_results:
            # Tool results — one message per result (OpenAI-style)
            for tr in msg.tool_results:
                result.append({
                    "role": "tool",
                    "tool_call_id": tr.tool_call_id,
                    "content": tr.content,
                })
        elif msg.role == "user":
            result.append({"role": "user", "content": msg.text or ""})
        else:
            # Assistant message — may have text, tool_calls, or both
            assistant = {"role": "assistant", "content": msg.text or ""}
            if msg.tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            result.append(assistant)

    return result
```

## 3. Response parsing

Parse the response back to `AIResponse`. Normalise `stop_reason`:

```python
def _parse_response(self, response: Any) -> AIResponse:
    tool_calls = []
    text = None

    # Extract tool calls and text from the response
    # ...

    # Normalise stop_reason to our internal vocabulary
    if tool_calls:
        stop_reason = "tool_use"
    elif raw_stop_reason in ("stop", "end_turn"):
        stop_reason = "end_turn"
    elif raw_stop_reason in ("length", "max_tokens"):
        stop_reason = "max_tokens"
    else:
        stop_reason = raw_stop_reason

    return AIResponse(
        stop_reason=stop_reason,
        text=text,
        tool_calls=tool_calls,
        input_tokens=usage.input_tokens,    # report usage — LLM_BUDGET_USD depends on it
        output_tokens=usage.output_tokens,
    )
```

## 4. Add retry logic

Rate limits happen. Add exponential backoff:

```python
def _call_with_retry(self, kwargs: dict) -> Any:
    delay = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            return self._client.call(**kwargs)
        except RateLimitError:
            if attempt < MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= 2
            else:
                raise
```

## 5. Wire it up

Each runtime builds its provider in a `_build_ai_provider()` function. Add a branch to each one you
want to support: `entrypoints/aws_lambda.py`, `gcp_cloudrun.py`, `azure_function.py`, and
`cli_chat.py` (chat mode). `argus scan` goes through the runtime entrypoints, so it picks this up.

```python
def _build_ai_provider():
    provider_name = os.environ.get("AI_PROVIDER", "bedrock").lower()
    if provider_name == "myprovider":
        from ai.myprovider import MyProvider
        return MyProvider()
    # ... existing providers
```

Then register the name in the places that validate it:

- `entrypoints/cli.py` — the `--ai-provider` `choices` lists
- `core/validation.py` — the `known` provider set (and any required env vars)
- `core/token_tracker.py` — per-million-token pricing, so budget tracking and cost estimates work
- `core/config.py` — any new settings, and the model default in `AISettings.resolved_model()`

Add to `.env.example`:

```ini
# MyProvider
MYPROVIDER_API_KEY=...
```

## 6. Write tests

```python title="tests/ai/test_myprovider.py"
from unittest.mock import MagicMock, patch
from ai.myprovider import MyProvider
from ai.base import Message, Tool

def test_parses_tool_call_response():
    mock_client = MagicMock()
    mock_client.call.return_value = _make_tool_call_response(...)

    with patch("ai.myprovider.MySDK") as mock_sdk:
        mock_sdk.return_value = mock_client
        provider = MyProvider(api_key="fake-key")

    response = provider.chat(
        messages=[Message(role="user", text="Go")],
        tools=[Tool(name="list_resources", description="...", input_schema={})],
    )

    assert response.stop_reason == "tool_use"
    assert response.tool_calls[0].name == "list_resources"
```

Cover: tool call parsing, text response parsing, system prompt injection, tool results as correct role, retry on rate limit, raise after max retries.
