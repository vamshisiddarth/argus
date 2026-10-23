"""AI_MAX_TOKENS reaches every provider, clamped to what the default model allows."""

from unittest.mock import MagicMock, patch

from ai.azure_openai import AzureOpenAIProvider
from ai.bedrock import BedrockProvider
from ai.vertexai import VertexAIProvider


def _bedrock(**kw):
    session = MagicMock()
    return BedrockProvider(session=session, **kw)


def _vertex(**kw):
    with (
        patch("ai.vertexai.openai"),
        patch("ai.vertexai.google.auth.default") as auth,
        patch("ai.vertexai.google.auth.transport.requests.Request"),
    ):
        creds = MagicMock(token="t", valid=True)
        auth.return_value = (creds, "p")
        return VertexAIProvider(project="p", **kw)


def _azure(**kw):
    with patch("ai.azure_openai.openai"):
        return AzureOpenAIProvider(
            endpoint="https://x.openai.azure.com/", api_key="k", **kw
        )


class TestBedrock:
    def test_default_is_ai_max_tokens(self):
        assert _bedrock()._max_tokens == 16000

    def test_ai_max_tokens_env(self, monkeypatch):
        monkeypatch.setenv("AI_MAX_TOKENS", "9000")
        assert _bedrock()._max_tokens == 9000

    def test_bedrock_specific_setting_is_no_longer_ignored(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_MAX_TOKENS", "3000")
        monkeypatch.setenv("AI_MAX_TOKENS", "9000")
        assert _bedrock()._max_tokens == 3000

    def test_explicit_argument_wins(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_MAX_TOKENS", "3000")
        assert _bedrock(max_tokens=1234)._max_tokens == 1234


class TestVertex:
    def test_default_is_clamped_to_the_default_model_limit(self):
        assert _vertex()._max_tokens == 8192

    def test_smaller_setting_is_respected(self, monkeypatch):
        monkeypatch.setenv("AI_MAX_TOKENS", "4000")
        assert _vertex()._max_tokens == 4000

    def test_explicit_argument_wins(self):
        assert _vertex(max_tokens=20000)._max_tokens == 20000


class TestAzureOpenAI:
    def test_default_fits_the_model_limit(self):
        assert _azure()._max_tokens == 16000

    def test_setting_above_the_model_limit_is_clamped(self, monkeypatch):
        monkeypatch.setenv("AI_MAX_TOKENS", "30000")
        assert _azure()._max_tokens == 16384

    def test_explicit_argument_wins(self):
        assert _azure(max_tokens=2000)._max_tokens == 2000
