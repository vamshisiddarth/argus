"""
Tests for BedrockProvider.
All AWS calls are mocked — no real Bedrock credentials required.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from ai.base import Message, Tool, ToolCall, ToolResult
from ai.bedrock import BedrockProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(mock_client: MagicMock) -> BedrockProvider:
    """Return a BedrockProvider whose boto3 client is pre-replaced."""
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    return BedrockProvider(session=mock_session)


def _tool_use_response(tool_use_id="tu-1", name="list_resources", input_=None):
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": name,
                            "input": input_ or {"regions": ["us-east-1"]},
                        }
                    }
                ]
            }
        },
    }


def _text_response(text="All clear."):
    return {
        "stopReason": "end_turn",
        "output": {"message": {"content": [{"text": text}]}},
    }


def _mixed_response(text="Thinking...", tool_use_id="tu-2", name="get_metrics"):
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "content": [
                    {"text": text},
                    {
                        "toolUse": {
                            "toolUseId": tool_use_id,
                            "name": name,
                            "input": {
                                "resource_id": "i-0abc",
                                "resource_type": "AWS::EC2::Instance",
                            },
                        }
                    },
                ]
            }
        },
    }


SAMPLE_TOOL = Tool(
    name="list_resources",
    description="List all cloud resources.",
    input_schema={
        "type": "object",
        "properties": {"regions": {"type": "array", "items": {"type": "string"}}},
        "required": ["regions"],
    },
)


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_parses_tool_use_block(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = _tool_use_response()
        provider = _make_provider(mock_client)

        response = provider.chat(
            messages=[Message(role="user", text="go")],
            tools=[SAMPLE_TOOL],
        )

        assert response.stop_reason == "tool_use"
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].id == "tu-1"
        assert response.tool_calls[0].name == "list_resources"
        assert response.tool_calls[0].arguments == {"regions": ["us-east-1"]}
        assert response.text is None

    def test_parses_text_response(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = _text_response("No idle resources found.")
        provider = _make_provider(mock_client)

        response = provider.chat(
            messages=[Message(role="user", text="go")],
            tools=[],
        )

        assert response.stop_reason == "end_turn"
        assert response.text == "No idle resources found."
        assert response.tool_calls == []

    def test_parses_mixed_text_and_tool_use(self):
        mock_client = MagicMock()
        mock_client.converse.return_value = _mixed_response()
        provider = _make_provider(mock_client)

        response = provider.chat(
            messages=[Message(role="user", text="go")],
            tools=[SAMPLE_TOOL],
        )

        assert response.text == "Thinking..."
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_metrics"


# ---------------------------------------------------------------------------
# Message serialisation tests
# ---------------------------------------------------------------------------


class TestMessageSerialisation:
    def _capture_converse_kwargs(
        self, mock_client: MagicMock, messages, tools, system=None
    ):
        mock_client.converse.return_value = _text_response()
        provider = _make_provider(mock_client)
        provider.chat(messages=messages, tools=tools, system_prompt=system)
        return mock_client.converse.call_args.kwargs

    def test_user_text_message_format(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[Message(role="user", text="hello")],
            tools=[],
        )
        assert kwargs["messages"][0] == {
            "role": "user",
            "content": [{"text": "hello"}],
        }

    def test_assistant_tool_call_message_format(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[
                Message(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            id="tc-1",
                            name="get_cost",
                            arguments={"resource_ids": ["i-0abc"]},
                        )
                    ],
                )
            ],
            tools=[],
        )
        content = kwargs["messages"][0]["content"]
        assert content[0] == {
            "toolUse": {
                "toolUseId": "tc-1",
                "name": "get_cost",
                "input": {"resource_ids": ["i-0abc"]},
            }
        }

    def test_user_tool_result_message_format(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[
                Message(
                    role="user",
                    tool_results=[
                        ToolResult(tool_call_id="tc-1", content='{"ok": true}')
                    ],
                )
            ],
            tools=[],
        )
        content = kwargs["messages"][0]["content"]
        assert content[0] == {
            "toolResult": {
                "toolUseId": "tc-1",
                "content": [{"text": '{"ok": true}'}],
            }
        }

    def test_error_tool_result_includes_status(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[
                Message(
                    role="user",
                    tool_results=[
                        ToolResult(tool_call_id="tc-1", content="boom", is_error=True)
                    ],
                )
            ],
            tools=[],
        )
        result_block = kwargs["messages"][0]["content"][0]["toolResult"]
        assert result_block["status"] == "error"

    def test_system_prompt_passed_correctly(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[Message(role="user", text="go")],
            tools=[],
            system="You are a cost analyst.",
        )
        assert kwargs["system"] == [{"text": "You are a cost analyst."}]

    def test_no_system_key_when_prompt_is_none(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[Message(role="user", text="go")],
            tools=[],
        )
        assert "system" not in kwargs

    def test_tool_config_absent_when_no_tools(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[Message(role="user", text="go")],
            tools=[],
        )
        assert "toolConfig" not in kwargs

    def test_tool_config_present_when_tools_provided(self):
        mock_client = MagicMock()
        kwargs = self._capture_converse_kwargs(
            mock_client,
            messages=[Message(role="user", text="go")],
            tools=[SAMPLE_TOOL],
        )
        assert "toolConfig" in kwargs
        spec = kwargs["toolConfig"]["tools"][0]["toolSpec"]
        assert spec["name"] == "list_resources"
        assert "json" in spec["inputSchema"]


# ---------------------------------------------------------------------------
# Retry / throttling tests
# ---------------------------------------------------------------------------


class TestThrottlingRetry:
    def test_retries_on_throttling_and_succeeds(self):
        mock_client = MagicMock()
        throttle_error = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse",
        )
        mock_client.converse.side_effect = [
            throttle_error,
            _text_response("ok"),
        ]
        provider = _make_provider(mock_client)

        with patch("ai.bedrock.time.sleep") as mock_sleep:
            response = provider.chat(
                messages=[Message(role="user", text="go")],
                tools=[],
            )

        assert mock_client.converse.call_count == 2
        mock_sleep.assert_called_once()
        assert response.text == "ok"

    def test_raises_after_max_retries_exceeded(self):
        mock_client = MagicMock()
        throttle_error = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse",
        )
        mock_client.converse.side_effect = [
            throttle_error,
            throttle_error,
            throttle_error,
        ]
        provider = _make_provider(mock_client)

        with patch("ai.bedrock.time.sleep"):
            with pytest.raises(ClientError) as exc_info:
                provider.chat(messages=[Message(role="user", text="go")], tools=[])

        assert exc_info.value.response["Error"]["Code"] == "ThrottlingException"
        assert mock_client.converse.call_count == 3

    def test_non_throttling_error_raises_immediately(self):
        mock_client = MagicMock()
        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad input"}},
            "Converse",
        )
        provider = _make_provider(mock_client)

        with pytest.raises(ClientError) as exc_info:
            provider.chat(messages=[Message(role="user", text="go")], tools=[])

        assert mock_client.converse.call_count == 1
        assert exc_info.value.response["Error"]["Code"] == "ValidationException"

    def test_retry_uses_exponential_backoff(self):
        mock_client = MagicMock()
        throttle = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse",
        )
        mock_client.converse.side_effect = [throttle, throttle, _text_response()]
        provider = _make_provider(mock_client)

        sleep_calls = []
        with patch(
            "ai.bedrock.time.sleep", side_effect=lambda s: sleep_calls.append(s)
        ):
            provider.chat(messages=[Message(role="user", text="go")], tools=[])

        assert len(sleep_calls) == 2
        assert sleep_calls[1] == sleep_calls[0] * 2
