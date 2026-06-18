"""Tests for core/validation.py — no cloud SDK calls needed."""

from __future__ import annotations

import json

import pytest

from core.validation import ConfigurationError, validate_environment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_AWS_ENV = {
    "AI_PROVIDER": "anthropic",
    "ANTHROPIC_API_KEY": "sk-ant-test-key",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
    "ACCOUNTS_MODE": "single",
}

VALID_GCP_ENV = {
    "AI_PROVIDER": "anthropic",
    "ANTHROPIC_API_KEY": "sk-ant-test-key",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
    "GCP_PROJECT_ID": "my-project-123",
}

VALID_AZURE_ENV = {
    "AI_PROVIDER": "anthropic",
    "ANTHROPIC_API_KEY": "sk-ant-test-key",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/X",
    "AZURE_SUBSCRIPTION_IDS": "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa",
}


def _set(monkeypatch, env: dict[str, str]) -> None:
    """Apply env dict; clear all keys from the full union before setting."""
    all_keys = {
        "AI_PROVIDER",
        "ANTHROPIC_API_KEY",
        "SLACK_WEBHOOK_URL",
        "DRY_RUN",
        "ACCOUNTS_MODE",
        "ACCOUNTS_CONFIG",
        "GCP_PROJECT_ID",
        "AZURE_SUBSCRIPTION_IDS",
        "AZURE_OPENAI_ENDPOINT",
    }
    for k in all_keys:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_aws_single_account(self, monkeypatch):
        _set(monkeypatch, VALID_AWS_ENV)
        validate_environment("aws")  # no exception

    def test_valid_aws_dry_run_no_slack_needed(self, monkeypatch):
        env = {**VALID_AWS_ENV, "DRY_RUN": "true"}
        env.pop("SLACK_WEBHOOK_URL", None)
        _set(monkeypatch, env)
        validate_environment("aws")

    def test_valid_gcp(self, monkeypatch):
        _set(monkeypatch, VALID_GCP_ENV)
        validate_environment("gcp")

    def test_valid_azure(self, monkeypatch):
        _set(monkeypatch, VALID_AZURE_ENV)
        validate_environment("azure")

    def test_no_ai_provider_set_is_ok(self, monkeypatch):
        """Empty AI_PROVIDER means the entrypoint picks the cloud-native default."""
        env = {**VALID_AWS_ENV}
        env.pop("AI_PROVIDER")
        _set(monkeypatch, env)
        validate_environment("aws")

    def test_valid_multi_account(self, monkeypatch):
        accounts = json.dumps(
            [
                {
                    "id": "111122223333",
                    "name": "dev",
                    "role_arn": "arn:aws:iam::111:role/R",
                }
            ]  # noqa: E501
        )
        env = {**VALID_AWS_ENV, "ACCOUNTS_MODE": "multi", "ACCOUNTS_CONFIG": accounts}
        _set(monkeypatch, env)
        validate_environment("aws")


# ---------------------------------------------------------------------------
# AI provider validation
# ---------------------------------------------------------------------------


class TestAIProviderValidation:
    def test_missing_anthropic_key_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV}
        env.pop("ANTHROPIC_API_KEY")
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            validate_environment("aws")

    def test_malformed_anthropic_key_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV, "ANTHROPIC_API_KEY": "bad-key-format"}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="malformed"):
            validate_environment("aws")

    def test_unknown_ai_provider_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV, "AI_PROVIDER": "openai"}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="not recognised"):
            validate_environment("aws")

    def test_azure_openai_missing_endpoint_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV, "AI_PROVIDER": "azure_openai"}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="AZURE_OPENAI_ENDPOINT"):
            validate_environment("aws")

    def test_azure_openai_bad_endpoint_raises(self, monkeypatch):
        env = {
            **VALID_AWS_ENV,
            "AI_PROVIDER": "azure_openai",
            "AZURE_OPENAI_ENDPOINT": "not-a-url",
        }
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="not a valid HTTPS URL"):
            validate_environment("aws")


# ---------------------------------------------------------------------------
# Slack validation
# ---------------------------------------------------------------------------


class TestSlackValidation:
    def test_missing_webhook_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV}
        env.pop("SLACK_WEBHOOK_URL")
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="SLACK_WEBHOOK_URL"):
            validate_environment("aws")

    def test_invalid_webhook_url_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV, "SLACK_WEBHOOK_URL": "http://not-https.com/hook"}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="not a valid HTTPS URL"):
            validate_environment("aws")

    def test_dry_run_skips_webhook_check(self, monkeypatch):
        env = {**VALID_AWS_ENV, "DRY_RUN": "true"}
        env.pop("SLACK_WEBHOOK_URL")
        _set(monkeypatch, env)
        validate_environment("aws")  # no exception


# ---------------------------------------------------------------------------
# AWS-specific validation
# ---------------------------------------------------------------------------


class TestAWSValidation:
    def test_invalid_accounts_mode_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV, "ACCOUNTS_MODE": "both"}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="ACCOUNTS_MODE"):
            validate_environment("aws")

    def test_multi_missing_accounts_config_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV, "ACCOUNTS_MODE": "multi"}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="ACCOUNTS_CONFIG"):
            validate_environment("aws")

    def test_multi_invalid_json_raises(self, monkeypatch):
        bad = "{bad json"
        env = {**VALID_AWS_ENV, "ACCOUNTS_MODE": "multi", "ACCOUNTS_CONFIG": bad}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="not valid JSON"):
            validate_environment("aws")

    def test_multi_empty_array_raises(self, monkeypatch):
        env = {**VALID_AWS_ENV, "ACCOUNTS_MODE": "multi", "ACCOUNTS_CONFIG": "[]"}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="non-empty"):
            validate_environment("aws")

    def test_multi_missing_role_arn_raises(self, monkeypatch):
        accounts = json.dumps([{"id": "111122223333", "name": "dev"}])
        env = {**VALID_AWS_ENV, "ACCOUNTS_MODE": "multi", "ACCOUNTS_CONFIG": accounts}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="role_arn"):
            validate_environment("aws")

    def test_multi_missing_id_raises(self, monkeypatch):
        accounts = json.dumps([{"name": "dev", "role_arn": "arn:aws:iam::111:role/R"}])
        env = {**VALID_AWS_ENV, "ACCOUNTS_MODE": "multi", "ACCOUNTS_CONFIG": accounts}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="id"):
            validate_environment("aws")


# ---------------------------------------------------------------------------
# GCP-specific validation
# ---------------------------------------------------------------------------


class TestGCPValidation:
    def test_missing_project_id_raises(self, monkeypatch):
        env = {**VALID_GCP_ENV}
        env.pop("GCP_PROJECT_ID")
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="GCP_PROJECT_ID"):
            validate_environment("gcp")


# ---------------------------------------------------------------------------
# Azure-specific validation
# ---------------------------------------------------------------------------


class TestAzureValidation:
    def test_missing_subscription_ids_raises(self, monkeypatch):
        env = {**VALID_AZURE_ENV}
        env.pop("AZURE_SUBSCRIPTION_IDS")
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="AZURE_SUBSCRIPTION_IDS"):
            validate_environment("azure")

    def test_blank_subscription_ids_raises(self, monkeypatch):
        env = {**VALID_AZURE_ENV, "AZURE_SUBSCRIPTION_IDS": "  ,  ,  "}
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError, match="AZURE_SUBSCRIPTION_IDS"):
            validate_environment("azure")


# ---------------------------------------------------------------------------
# Error accumulation
# ---------------------------------------------------------------------------


class TestErrorAccumulation:
    def test_multiple_errors_reported_together(self, monkeypatch):
        """Validation collects all errors and reports them in one exception."""
        env = {
            "AI_PROVIDER": "anthropic",
            # missing ANTHROPIC_API_KEY
            # missing SLACK_WEBHOOK_URL
            # missing GCP_PROJECT_ID
        }
        _set(monkeypatch, env)
        with pytest.raises(ConfigurationError) as exc_info:
            validate_environment("gcp")
        msg = str(exc_info.value)
        assert "ANTHROPIC_API_KEY" in msg
        assert "SLACK_WEBHOOK_URL" in msg
        assert "GCP_PROJECT_ID" in msg
        assert "3 configuration error(s)" in msg
