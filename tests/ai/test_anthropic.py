from unittest.mock import MagicMock, patch

import pytest

from ai.anthropic import AnthropicProvider
from ai.base import AIResponse, Message, Tool, ToolCall, ToolResult

# ------------------------------------------------------------------
# Fixtures — mimic real Anthropic SDK response objects
# ------------------------------------------------------------------


def _make_sdk_text_response(text: str, stop_reason: str = "end_turn"):
    block = MagicMock()
    block.type = "text"
    block.text = text

    response = MagicMock()
    response.stop_reason = stop_reason
    response.content = [block]
    return response


def _make_sdk_tool_use_response(tool_id: str, tool_name: str, tool_input: dict):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = tool_input

    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def _make_sdk_mixed_response(text: str, tool_id: str, tool_name: str, tool_input: dict):
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = tool_id
    tool_block.name = tool_name
    tool_block.input = tool_input

    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [text_block, tool_block]
    return response


SAMPLE_TOOL = Tool(
    name="list_resources",
    description="List all cloud resources",
    input_schema={
        "type": "object",
        "properties": {"regions": {"type": "array", "items": {"type": "string"}}},
        "required": ["regions"],
    },
)

# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestAnthropicProviderInit:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider(api_key=None)

    def test_accepts_explicit_api_key(self):
        with patch("ai.anthropic.anthropic_sdk.Anthropic"):
            provider = AnthropicProvider(api_key="sk-ant-test")
        assert provider is not None

    def test_uses_default_model(self):
        with patch("ai.anthropic.anthropic_sdk.Anthropic"):
            provider = AnthropicProvider(api_key="sk-ant-test")
        assert provider._model == AnthropicProvider.DEFAULT_MODEL


class TestChatEndTurn:
    def test_returns_text_response(self):
        with patch("ai.anthropic.anthropic_sdk.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create.return_value = _make_sdk_text_response(
                "Analysis complete."
            )

            provider = AnthropicProvider(api_key="sk-ant-test")
            messages = [Message(role="user", text="Begin analysis.")]
            result = provider.chat(messages, [SAMPLE_TOOL])

        assert isinstance(result, AIResponse)
        assert result.stop_reason == "end_turn"
        assert result.text == "Analysis complete."
        assert result.tool_calls == []

    def test_system_prompt_passed_to_sdk(self):
        with patch("ai.anthropic.anthropic_sdk.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create.return_value = _make_sdk_text_response("ok")

            provider = AnthropicProvider(api_key="sk-ant-test")
            provider.chat(
                [Message(role="user", text="go")],
                [SAMPLE_TOOL],
                system_prompt="You are a cost agent.",
            )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        # system is sent as a cache_control block for prompt caching
        system = call_kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["text"] == "You are a cost agent."
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_no_system_param_when_prompt_is_none(self):
        with patch("ai.anthropic.anthropic_sdk.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create.return_value = _make_sdk_text_response("ok")

            provider = AnthropicProvider(api_key="sk-ant-test")
            provider.chat([Message(role="user", text="go")], [SAMPLE_TOOL])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs


class TestChatToolUse:
    def test_parses_tool_call(self):
        with patch("ai.anthropic.anthropic_sdk.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create.return_value = _make_sdk_tool_use_response(
                tool_id="toolu_01",
                tool_name="list_resources",
                tool_input={"regions": ["us-east-1"]},
            )

            provider = AnthropicProvider(api_key="sk-ant-test")
            result = provider.chat([Message(role="user", text="go")], [SAMPLE_TOOL])

        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "toolu_01"
        assert result.tool_calls[0].name == "list_resources"
        assert result.tool_calls[0].arguments == {"regions": ["us-east-1"]}

    def test_parses_mixed_text_and_tool_call(self):
        with patch("ai.anthropic.anthropic_sdk.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client
            mock_client.messages.create.return_value = _make_sdk_mixed_response(
                text="Let me check the resources first.",
                tool_id="toolu_02",
                tool_name="list_resources",
                tool_input={"regions": ["us-west-2"]},
            )

            provider = AnthropicProvider(api_key="sk-ant-test")
            result = provider.chat([Message(role="user", text="go")], [SAMPLE_TOOL])

        assert result.text == "Let me check the resources first."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "list_resources"


class TestMessageConversion:
    def _get_converted_messages(self, messages, mock_client) -> list:
        mock_client.messages.create.return_value = _make_sdk_text_response("ok")
        with patch("ai.anthropic.anthropic_sdk.Anthropic") as mock_anthropic:
            mock_anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="sk-ant-test")
            provider.chat(messages, [])
        return mock_client.messages.create.call_args.kwargs["messages"]

    def test_simple_user_message(self):
        mock_client = MagicMock()
        converted = self._get_converted_messages(
            [Message(role="user", text="Hello")], mock_client
        )
        assert converted == [{"role": "user", "content": "Hello"}]

    def test_tool_result_message(self):
        mock_client = MagicMock()
        converted = self._get_converted_messages(
            [
                Message(
                    role="user",
                    tool_results=[
                        ToolResult(tool_call_id="toolu_01", content='["resource-1"]')
                    ],
                )
            ],
            mock_client,
        )
        assert converted[0]["role"] == "user"
        assert converted[0]["content"][0]["type"] == "tool_result"
        assert converted[0]["content"][0]["tool_use_id"] == "toolu_01"

    def test_error_tool_result_includes_is_error(self):
        mock_client = MagicMock()
        converted = self._get_converted_messages(
            [
                Message(
                    role="user",
                    tool_results=[
                        ToolResult(
                            tool_call_id="toolu_01",
                            content="Something went wrong",
                            is_error=True,
                        )
                    ],
                )
            ],
            mock_client,
        )
        assert converted[0]["content"][0]["is_error"] is True

    def test_assistant_message_with_tool_call(self):
        mock_client = MagicMock()
        converted = self._get_converted_messages(
            [
                Message(
                    role="assistant",
                    text="Checking resources...",
                    tool_calls=[
                        ToolCall(
                            id="toolu_01",
                            name="list_resources",
                            arguments={"regions": ["us-east-1"]},
                        )
                    ],
                )
            ],
            mock_client,
        )
        content = converted[0]["content"]
        assert content[0] == {"type": "text", "text": "Checking resources..."}
        assert content[1]["type"] == "tool_use"
        assert content[1]["id"] == "toolu_01"
        assert content[1]["input"] == {"regions": ["us-east-1"]}
