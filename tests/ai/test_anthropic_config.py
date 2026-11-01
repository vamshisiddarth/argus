"""Output cap, timeout and retry behaviour of the Anthropic provider."""

from unittest.mock import MagicMock, patch

import anthropic as anthropic_sdk
import pytest

from ai.anthropic import AnthropicProvider
from ai.base import Message


def _response():
    block = MagicMock(type="text", text="hi")
    return MagicMock(stop_reason="end_turn", content=[block], usage=None)


def _provider(create=None, **env):
    client = MagicMock()
    client.messages.create = create or MagicMock(return_value=_response())
    with patch("ai.anthropic.anthropic_sdk.Anthropic", return_value=client) as sdk_cls:
        provider = AnthropicProvider(api_key="test-key")
    return provider, client, sdk_cls


def test_default_max_tokens_is_16000():
    provider, client, _ = _provider()

    provider.chat([Message(role="user", text="x")], [])

    assert client.messages.create.call_args.kwargs["max_tokens"] == 16000


def test_max_tokens_comes_from_ai_max_tokens(monkeypatch):
    monkeypatch.setenv("AI_MAX_TOKENS", "8000")
    provider, client, _ = _provider()

    provider.chat([Message(role="user", text="x")], [])

    assert client.messages.create.call_args.kwargs["max_tokens"] == 8000


def test_explicit_constructor_value_wins(monkeypatch):
    monkeypatch.setenv("AI_MAX_TOKENS", "8000")
    client = MagicMock()
    client.messages.create = MagicMock(return_value=_response())
    with patch("ai.anthropic.anthropic_sdk.Anthropic", return_value=client):
        provider = AnthropicProvider(api_key="k", max_tokens=1234)

    provider.chat([Message(role="user", text="x")], [])

    assert client.messages.create.call_args.kwargs["max_tokens"] == 1234


def test_default_timeout_is_600_seconds():
    _, _, sdk_cls = _provider()
    assert sdk_cls.call_args.kwargs["timeout"] == 600.0


def test_timeout_comes_from_ai_timeout_seconds(monkeypatch):
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "90")
    _, _, sdk_cls = _provider()
    assert sdk_cls.call_args.kwargs["timeout"] == 90.0


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: anthropic_sdk.APITimeoutError(request=MagicMock()),
        lambda: anthropic_sdk.APIConnectionError(request=MagicMock()),
    ],
)
@patch("ai.anthropic.time.sleep")
def test_timeouts_and_connection_errors_are_retried(mock_sleep, error_factory):
    create = MagicMock(side_effect=[error_factory(), _response()])
    provider, _, _ = _provider(create=create)

    result = provider.chat([Message(role="user", text="x")], [])

    assert create.call_count == 2
    mock_sleep.assert_called_once()
    assert result.text == "hi"


@patch("ai.anthropic.time.sleep")
def test_timeout_is_raised_after_max_retries(mock_sleep):
    err = anthropic_sdk.APITimeoutError(request=MagicMock())
    create = MagicMock(side_effect=err)
    provider, _, _ = _provider(create=create)

    with pytest.raises(anthropic_sdk.APITimeoutError):
        provider.chat([Message(role="user", text="x")], [])


class TestCachedPromptTokensAreCounted:
    """usage.input_tokens excludes cached prompt tokens; spend must not."""

    def _usage_response(self, **usage):
        block = MagicMock(type="text", text="hi")
        return MagicMock(
            stop_reason="end_turn",
            content=[block],
            usage=MagicMock(
                input_tokens=usage.get("input", 500),
                output_tokens=usage.get("output", 50),
                cache_creation_input_tokens=usage.get("creation", 0),
                cache_read_input_tokens=usage.get("read", 0),
            ),
        )

    def _chat(self, **usage):
        create = MagicMock(return_value=self._usage_response(**usage))
        provider, _, _ = _provider(create=create)
        return provider.chat([Message(role="user", text="x")], [])

    def test_uncached_usage_is_unchanged(self):
        assert self._chat().input_tokens == 500

    def test_cache_writes_cost_a_quarter_more_than_plain_input(self):
        # 500 plain + 2000 written to cache -> 500 + 2000 * 1.25
        assert self._chat(creation=2000).input_tokens == 3000

    def test_cache_reads_cost_a_tenth(self):
        # 500 plain + 2000 read from cache -> 500 + 2000 * 0.1
        assert self._chat(read=2000).input_tokens == 700

    def test_missing_cache_fields_do_not_break(self):
        block = MagicMock(type="text", text="hi")
        usage = MagicMock(spec=["input_tokens", "output_tokens"])
        usage.input_tokens, usage.output_tokens = 10, 5
        create = MagicMock(
            return_value=MagicMock(stop_reason="end_turn", content=[block], usage=usage)
        )
        provider, _, _ = _provider(create=create)

        assert provider.chat([Message(role="user", text="x")], []).input_tokens == 10
