from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.secrets import resolve_secrets


class TestResolveSecretsNoOp:
    def test_no_secret_vars_set(self, monkeypatch):
        for var in (
            "ANTHROPIC_API_KEY",
            "SLACK_WEBHOOK_URL",
            "TEAMS_WEBHOOK_URL",
            "WEBHOOK_URL",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
        ):
            monkeypatch.delenv(var, raising=False)
        resolve_secrets()

    def test_plain_values_unchanged(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-key")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/xxx")
        resolve_secrets()
        import os

        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-real-key"
        assert os.environ["SLACK_WEBHOOK_URL"] == "https://hooks.slack.com/xxx"


class TestAWSSecretsManager:
    def test_resolves_arn(self, monkeypatch):
        arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:my-key"
        monkeypatch.setenv("ANTHROPIC_API_KEY", arn)

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": "sk-ant-resolved"}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        modules = {
            "boto3": mock_boto3,
            "botocore": MagicMock(),
            "botocore.exceptions": MagicMock(),
        }
        with patch.dict("sys.modules", modules):
            with patch("core.secrets.boto3", mock_boto3, create=True):
                import core.secrets as mod

                # Directly test the resolver
                result = mod._resolve_aws("ANTHROPIC_API_KEY", arn)

        assert result == "sk-ant-resolved"
        mock_boto3.client.assert_called_once_with(
            "secretsmanager", region_name="us-east-1"
        )

    def test_arn_pattern_matching(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-an-arn")
        resolve_secrets()
        import os

        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-not-an-arn"


class TestGCPSecretManager:
    def test_gcp_pattern_with_version(self):
        from core.secrets import _GCP_PATTERN

        m = _GCP_PATTERN.match("gcp-secret://my-proj/my-secret/2")
        assert m is not None
        assert m.group(1) == "my-proj"
        assert m.group(2) == "my-secret"
        assert m.group(3) == "2"

    def test_gcp_pattern_without_version(self):
        from core.secrets import _GCP_PATTERN

        m = _GCP_PATTERN.match("gcp-secret://my-proj/my-secret")
        assert m is not None
        assert m.group(3) is None


class TestAzureKeyVault:
    def test_akv_pattern(self):
        from core.secrets import _AKV_PATTERN

        m = _AKV_PATTERN.match("akv://my-vault/my-secret")
        assert m is not None
        assert m.group(1) == "my-vault"
        assert m.group(2) == "my-secret"

    def test_non_akv_value_ignored(self):
        from core.secrets import _AKV_PATTERN

        assert _AKV_PATTERN.match("https://example.com") is None


class TestPatternDetection:
    def test_aws_arn_detected(self):
        from core.secrets import _try_resolve

        with patch("core.secrets._resolve_aws", return_value="resolved") as mock:
            result = _try_resolve(
                "ANTHROPIC_API_KEY",
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:test",
            )
        assert result == "resolved"
        mock.assert_called_once()

    def test_gcp_reference_detected(self):
        from core.secrets import _try_resolve

        with patch("core.secrets._resolve_gcp", return_value="resolved") as mock:
            result = _try_resolve(
                "SLACK_WEBHOOK_URL",
                "gcp-secret://my-proj/webhook-url",
            )
        assert result == "resolved"
        mock.assert_called_once_with(
            "SLACK_WEBHOOK_URL", "my-proj", "webhook-url", "latest"
        )

    def test_akv_reference_detected(self):
        from core.secrets import _try_resolve

        with patch("core.secrets._resolve_azure", return_value="resolved") as mock:
            result = _try_resolve(
                "WEBHOOK_URL",
                "akv://my-vault/webhook-secret",
            )
        assert result == "resolved"
        mock.assert_called_once_with("WEBHOOK_URL", "my-vault", "webhook-secret")

    def test_plain_value_returns_none(self):
        from core.secrets import _try_resolve

        assert _try_resolve("ANTHROPIC_API_KEY", "sk-ant-real-key") is None
        assert _try_resolve("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x") is None

    def test_resolve_updates_environ(self, monkeypatch):
        monkeypatch.setenv(
            "ANTHROPIC_API_KEY",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:key",
        )
        with patch("core.secrets._resolve_aws", return_value="sk-ant-resolved"):
            resolve_secrets()
        import os

        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-resolved"
