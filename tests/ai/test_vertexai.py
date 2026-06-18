"""
Tests for VertexAIProvider.
All HTTP calls are mocked — no real GCP credentials required.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from ai.base import Message, Tool, ToolResult
from ai.vertexai import VertexAIProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_call_completion(tool_id="tc-1", name="list_resources", args=None):
    """Build a mock OpenAI-style completion with a tool call."""
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


def _make_provider(mock_openai_client: MagicMock) -> VertexAIProvider:
    """Instantiate VertexAIProvider with all external dependencies mocked."""
    with (
        patch("ai.vertexai.openai") as mock_openai_mod,
        patch("ai.vertexai.google.auth.default") as mock_auth,
        patch("ai.vertexai.google.auth.transport.requests.Request"),
    ):
        creds = MagicMock()
        creds.token = "fake-token"
        creds.valid = True
        mock_auth.return_value = (creds, "my-project")
        mock_openai_mod.OpenAI.return_value = mock_openai_client

        provider = VertexAIProvider(project="my-project")
        provider._client = mock_openai_client
        provider._credentials = creds
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVertexAIProvider:
    def test_raises_if_no_project(self, monkeypatch):
        monkeypatch.delenv("VERTEXAI_PROJECT", raising=False)
        with pytest.raises(EnvironmentError, match="VERTEXAI_PROJECT"):
            with (
                patch("ai.vertexai.openai"),
                patch("ai.vertexai.google.auth.default"),
                patch("ai.vertexai.google.auth.transport.requests.Request"),
            ):
                VertexAIProvider(project=None)

    def test_parses_tool_call_response(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_tool_call_completion(
            tool_id="tc-99",
            name="get_metrics",
            args={"resource_id": "i-0abc", "resource_type": "AWS::EC2::Instance"},
        )
        provider = _make_provider(mock_client)

        response = provider.chat(
            messages=[Message(role="user", text="Go")],
            tools=[Tool(name="get_metrics", description="...", input_schema={})],
        )

        assert response.stop_reason == "tool_use"
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_metrics"
        assert response.tool_calls[0].id == "tc-99"
        assert response.tool_calls[0].arguments["resource_id"] == "i-0abc"

    def test_parses_text_response(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_text_completion(
            "Scan complete."
        )
        provider = _make_provider(mock_client)

        response = provider.chat(
            messages=[Message(role="user", text="Go")],
            tools=[],
        )

        assert response.stop_reason == "end_turn"
        assert response.text == "Scan complete."
        assert response.tool_calls == []

    def test_system_prompt_injected_as_system_message(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_text_completion()
        provider = _make_provider(mock_client)

        provider.chat(
            messages=[Message(role="user", text="Hi")],
            tools=[],
            system_prompt="You are Argus.",
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are Argus."

    def test_tool_results_become_tool_role_messages(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_text_completion()
        provider = _make_provider(mock_client)

        provider.chat(
            messages=[
                Message(
                    role="user",
                    tool_results=[
                        ToolResult(tool_call_id="tc-1", content='{"id":"i-0abc"}'),
                    ],
                )
            ],
            tools=[],
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "tc-1"

    def test_retries_on_rate_limit(self):
        import openai

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            openai.RateLimitError("rate limited", response=MagicMock(), body={}),
            _make_text_completion("ok"),
        ]
        provider = _make_provider(mock_client)

        with patch("ai.vertexai.time.sleep"):
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
        provider = _make_provider(mock_client)

        with patch("ai.vertexai.time.sleep"):
            with pytest.raises(openai.RateLimitError):
                provider.chat(
                    messages=[Message(role="user", text="Go")],
                    tools=[],
                )
