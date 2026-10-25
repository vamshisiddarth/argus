"""The Anthropic SDK 2.x dropped `temperature` from Messages.create."""

from unittest.mock import MagicMock, patch

from ai.anthropic import AnthropicProvider
from ai.base import Message


def _provider(create):
    client = MagicMock()
    client.messages.create = create
    with patch("ai.anthropic.anthropic_sdk.Anthropic", return_value=client):
        return AnthropicProvider(api_key="test-key")


def _response():
    block = MagicMock(type="text", text="hi")
    return MagicMock(stop_reason="end_turn", content=[block], usage=None)


def test_temperature_is_omitted_when_the_sdk_does_not_accept_it():
    seen = {}

    def create(*, model, max_tokens, messages, tools=None, system=None):
        seen["called"] = True
        return _response()

    _provider(create).chat([Message(role="user", text="x")], [])

    assert seen == {"called": True}  # no TypeError for an unexpected keyword


def test_temperature_is_sent_when_the_sdk_accepts_it():
    seen = {}

    def create(*, model, max_tokens, temperature, messages, tools=None, system=None):
        seen["temperature"] = temperature
        return _response()

    _provider(create).chat([Message(role="user", text="x")], [])

    assert seen["temperature"] == 0.0
