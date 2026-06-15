"""
Tests for AzureOpenAIProvider.
All HTTP calls are mocked — no real Azure credentials required.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from ai.base import Message, Tool, ToolCall, ToolResult
from ai.azure_openai import AzureOpenAIProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call_completion(tool_id="tc-1", name="list_resources", args=None):
    tc = MagicMock()
    tc.id = tool_id
    tc.function.name = name
    tc.function.arguments = json.dumps(args or {"ignore_regions": []})

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message.content = None
    choice.message.tool_calls = [tc]

    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_text_completion(text="All done."):
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = text
    choice.message.tool_calls = None

    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_provider_with_key(mock_client: MagicMock) -> AzureOpenAIProvider:
    """Provider using an explicit API key (no managed identity)."""
    with patch("ai.azure_openai.openai") as mock_openai_mod:
        mock_openai_mod.AzureOpenAI.return_value = mock_client
        provider = AzureOpenAIProvider(
            endpoint="https://my-resource.openai.azure.com/",
            api_key="fake-key",
        )
        provider._client = mock_client
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAzureOpenAIProvider:
    def test_raises_if_no_endpoint(self, monkeypatch):
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
        with patch("ai.azure_openai.openai"):
            with pytest.raises(EnvironmentError, match="AZURE_OPENAI_ENDPOINT"):
                AzureOpenAIProvider(endpoint=None, api_key="key")

    def test_parses_tool_call_response(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_tool_call_completion(
            tool_id="tc-42", name="get_cost", args={"resource_ids": ["i-0abc"]}
        )
        provider = _make_provider_with_key(mock_client)

        response = provider.chat(
            messages=[Message(role="user", text="Go")],
            tools=[Tool(name="get_cost", description="...", input_schema={})],
        )

        assert response.stop_reason == "tool_use"
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_cost"
        assert response.tool_calls[0].id == "tc-42"
        assert response.tool_calls[0].arguments["resource_ids"] == ["i-0abc"]

    def test_parses_text_response(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_text_completion("Done.")
        provider = _make_provider_with_key(mock_client)

        response = provider.chat(
            messages=[Message(role="user", text="Go")],
            tools=[],
        )

        assert response.stop_reason == "end_turn"
        assert response.text == "Done."
        assert response.tool_calls == []

    def test_system_prompt_injected_as_system_message(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_text_completion()
        provider = _make_provider_with_key(mock_client)

        provider.chat(
            messages=[Message(role="user", text="Hi")],
            tools=[],
            system_prompt="You are Argus.",
        )

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are Argus."

    def test_tool_results_become_tool_role_messages(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_text_completion()
        provider = _make_provider_with_key(mock_client)

        provider.chat(
            messages=[
                Message(
                    role="user",
                    tool_results=[
                        ToolResult(tool_call_id="tc-1", content='[{"id":"i-0abc"}]'),
                    ],
                )
            ],
            tools=[],
        )

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "tc-1"

    def test_retries_on_rate_limit(self):
        import openai

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            openai.RateLimitError("rate limited", response=MagicMock(), body={}),
            _make_text_completion("ok"),
        ]
        provider = _make_provider_with_key(mock_client)

        with patch("ai.azure_openai.time.sleep"):
            response = provider.chat(
                messages=[Message(role="user", text="Go")],
                tools=[],
            )

        assert response.text == "ok"
        assert mock_client.chat.completions.create.call_count == 2

    def test_raises_after_max_retries(self):
        import openai

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.RateLimitError(
            "rate limited", response=MagicMock(), body={}
        )
        provider = _make_provider_with_key(mock_client)

        with patch("ai.azure_openai.time.sleep"):
            with pytest.raises(openai.RateLimitError):
                provider.chat(
                    messages=[Message(role="user", text="Go")],
                    tools=[],
                )

    def test_wraps_auth_error(self):
        import openai

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.AuthenticationError(
            "auth failed", response=MagicMock(), body={}
        )
        provider = _make_provider_with_key(mock_client)

        with pytest.raises(EnvironmentError, match="authentication failed"):
            provider.chat(
                messages=[Message(role="user", text="Go")],
                tools=[],
            )
