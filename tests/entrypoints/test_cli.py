"""
Tests for entrypoints/cli.py.
Mocks the Lambda handler and file I/O — no real cloud calls.
"""

from __future__ import annotations

import json
import os
from unittest.mock import mock_open, patch

import pytest

# ---------------------------------------------------------------------------
# main — aws cloud
# ---------------------------------------------------------------------------


class TestMainAWS:
    @patch("entrypoints.aws_lambda.handler")
    def test_aws_run_now_calls_handler(self, mock_handler, monkeypatch, capsys):
        mock_handler.return_value = {"statusCode": 200, "findings_count": 0}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now"])

        mock_handler.assert_called_once_with({}, None)
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["statusCode"] == 200

    @patch("entrypoints.aws_lambda.handler")
    def test_sets_ignore_regions_env_var(self, mock_handler, monkeypatch):
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(
            ["--cloud", "aws", "--run-now", "--ignore-regions", "ap-east-1,me-south-1"]
        )

        import os

        assert os.environ["IGNORE_REGIONS"] == "ap-east-1,me-south-1"

    @patch("entrypoints.aws_lambda.handler")
    def test_sets_primary_region_env_var(self, mock_handler, monkeypatch):
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now", "--primary-region", "eu-west-1"])

        import os

        assert os.environ["PRIMARY_REGION"] == "eu-west-1"

    @patch("entrypoints.aws_lambda.handler")
    def test_default_primary_region_is_us_east_1(self, mock_handler, monkeypatch):
        monkeypatch.delenv("PRIMARY_REGION", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now"])

        import os

        assert os.environ["PRIMARY_REGION"] == "us-east-1"


# ---------------------------------------------------------------------------
# main — --dry-run
# ---------------------------------------------------------------------------


class TestMainDryRun:
    @patch("entrypoints.aws_lambda.handler")
    def test_dry_run_sets_env_var(self, mock_handler, monkeypatch):
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now", "--dry-run"])

        import os

        assert os.environ["DRY_RUN"] == "true"

    @patch("entrypoints.aws_lambda.handler")
    def test_no_dry_run_does_not_set_env_var(self, mock_handler, monkeypatch):
        monkeypatch.delenv("DRY_RUN", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now"])

        import os

        assert os.environ.get("DRY_RUN") != "true"


# ---------------------------------------------------------------------------
# main — --ai-provider
# ---------------------------------------------------------------------------


class TestMainAIProvider:
    @patch("entrypoints.aws_lambda.handler")
    def test_anthropic_provider_sets_env_var(self, mock_handler, monkeypatch):
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now", "--ai-provider", "anthropic"])

        import os

        assert os.environ["AI_PROVIDER"] == "anthropic"

    @patch("entrypoints.aws_lambda.handler")
    def test_bedrock_provider_sets_env_var(self, mock_handler, monkeypatch):
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now", "--ai-provider", "bedrock"])

        import os

        assert os.environ["AI_PROVIDER"] == "bedrock"

    @patch("entrypoints.aws_lambda.handler")
    def test_default_ai_provider_is_anthropic(self, mock_handler, monkeypatch):
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now"])

        import os

        assert os.environ["AI_PROVIDER"] == "anthropic"


# ---------------------------------------------------------------------------
# main — --accounts
# ---------------------------------------------------------------------------


class TestMainAccounts:
    @patch("entrypoints.cli._apply_accounts_config")
    @patch("entrypoints.aws_lambda.handler")
    def test_accounts_flag_calls_apply_accounts_config(
        self, mock_handler, mock_apply, monkeypatch
    ):
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["--cloud", "aws", "--run-now", "--accounts", "accounts.yaml"])

        mock_apply.assert_called_once_with("accounts.yaml", "aws")


# ---------------------------------------------------------------------------
# _apply_accounts_config
# ---------------------------------------------------------------------------


class TestApplyAccountsConfig:
    @pytest.fixture(autouse=True)
    def _clean_accounts_env(self):
        yield
        for key in (
            "ACCOUNTS_MODE",
            "ACCOUNTS_CONFIG",
            "GCP_PROJECT_IDS",
            "AZURE_SUBSCRIPTION_IDS",
        ):
            os.environ.pop(key, None)

    def test_sets_single_mode_env_vars(self, monkeypatch):
        config = {"mode": "single"}

        with patch("builtins.open", mock_open()):
            with patch("yaml.safe_load", return_value=config):
                from entrypoints.cli import _apply_accounts_config

                _apply_accounts_config("accounts.yaml", "aws")

        import os

        assert os.environ["ACCOUNTS_MODE"] == "single"

    def test_sets_multi_mode_with_accounts_json(self, monkeypatch):
        config = {
            "mode": "multi",
            "accounts": [
                {"id": "111", "name": "dev", "role_arn": "arn:aws:iam::111:role/R"},
                {"id": "222", "name": "prod", "role_arn": "arn:aws:iam::222:role/R"},
            ],
        }

        with patch("builtins.open", mock_open()):
            with patch("yaml.safe_load", return_value=config):
                from entrypoints.cli import _apply_accounts_config

                _apply_accounts_config("accounts.yaml", "aws")

        import os

        assert os.environ["ACCOUNTS_MODE"] == "multi"
        parsed = json.loads(os.environ["ACCOUNTS_CONFIG"])
        assert len(parsed) == 2
        assert parsed[0]["id"] == "111"
        assert parsed[1]["id"] == "222"

    def test_defaults_to_single_when_mode_missing(self, monkeypatch):
        config = {}

        with patch("builtins.open", mock_open()):
            with patch("yaml.safe_load", return_value=config):
                from entrypoints.cli import _apply_accounts_config

                _apply_accounts_config("accounts.yaml", "aws")

        import os

        assert os.environ["ACCOUNTS_MODE"] == "single"

    def test_exits_when_pyyaml_not_installed(self, monkeypatch):
        import sys

        saved = sys.modules.get("yaml")
        try:
            with patch.dict("sys.modules", {"yaml": None}):
                import entrypoints.cli as cli_mod

                with pytest.raises(SystemExit) as exc_info:
                    cli_mod._apply_accounts_config("accounts.yaml", "aws")

                assert exc_info.value.code == 1
        finally:
            if saved is not None:
                sys.modules["yaml"] = saved

    def test_gcp_sets_project_ids_from_yaml(self, monkeypatch):
        config = {
            "mode": "multi",
            "projects": [
                {"id": "proj-dev", "name": "dev"},
                {"id": "proj-prod", "name": "production"},
            ],
        }

        with patch("builtins.open", mock_open()):
            with patch("yaml.safe_load", return_value=config):
                from entrypoints.cli import _apply_accounts_config

                _apply_accounts_config("accounts.yaml", "gcp")

        import os

        assert os.environ["ACCOUNTS_MODE"] == "multi"
        assert os.environ["GCP_PROJECT_IDS"] == "proj-dev,proj-prod"
        parsed = json.loads(os.environ["ACCOUNTS_CONFIG"])
        assert len(parsed) == 2
        assert parsed[0]["name"] == "dev"

    def test_azure_sets_subscription_ids_from_yaml(self, monkeypatch):
        config = {
            "mode": "multi",
            "subscriptions": [
                {"id": "sub-aaa", "name": "dev"},
                {"id": "sub-bbb", "name": "prod"},
            ],
        }

        with patch("builtins.open", mock_open()):
            with patch("yaml.safe_load", return_value=config):
                from entrypoints.cli import _apply_accounts_config

                _apply_accounts_config("accounts.yaml", "azure")

        import os

        assert os.environ["ACCOUNTS_MODE"] == "multi"
        assert os.environ["AZURE_SUBSCRIPTION_IDS"] == "sub-aaa,sub-bbb"
        parsed = json.loads(os.environ["ACCOUNTS_CONFIG"])
        assert len(parsed) == 2
        assert parsed[0]["name"] == "dev"


# ---------------------------------------------------------------------------
# main — invalid cloud (argparse should reject it)
# ---------------------------------------------------------------------------


class TestMainInvalidCloud:
    def test_invalid_cloud_exits(self):
        from entrypoints.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--cloud", "oracle", "--run-now"])

        # argparse exits with code 2 for invalid choices
        assert exc_info.value.code == 2

    def test_no_subcommand_prints_help_and_exits(self):
        from entrypoints.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--cloud", "aws"])

        # No subcommand → prints help and exits cleanly (code 0)
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# _detect_cloud — auto-detection from env vars
# ---------------------------------------------------------------------------


class TestDetectCloud:
    def test_detects_gcp_from_project_id(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        from entrypoints.cli import _detect_cloud

        assert _detect_cloud() == "gcp"

    def test_detects_azure_from_subscription_ids(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-1,sub-2")
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        from entrypoints.cli import _detect_cloud

        assert _detect_cloud() == "azure"

    def test_detects_aws_from_profile(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.setenv("AWS_PROFILE", "dev")
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        from entrypoints.cli import _detect_cloud

        assert _detect_cloud() == "aws"

    def test_detects_aws_from_access_key(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA...")
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        from entrypoints.cli import _detect_cloud

        assert _detect_cloud() == "aws"

    def test_detects_aws_from_default_region(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

        from entrypoints.cli import _detect_cloud

        assert _detect_cloud() == "aws"

    def test_returns_none_when_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        from entrypoints.cli import _detect_cloud

        assert _detect_cloud() is None

    def test_gcp_takes_priority_over_aws(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
        monkeypatch.setenv("AWS_PROFILE", "dev")

        from entrypoints.cli import _detect_cloud

        assert _detect_cloud() == "gcp"


class TestAutoDetectIntegration:
    @patch("entrypoints.aws_lambda.handler")
    def test_scan_auto_detects_aws(self, mock_handler, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.setenv("AWS_PROFILE", "test")
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["scan"])

        mock_handler.assert_called_once()

    def test_scan_exits_when_no_cloud_detected(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        from entrypoints.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["scan"])

        assert exc_info.value.code == 1

    @patch("entrypoints.aws_lambda.handler")
    def test_explicit_cloud_overrides_auto_detect(self, mock_handler, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
        mock_handler.return_value = {"statusCode": 200}

        from entrypoints.cli import main

        main(["scan", "--cloud", "aws"])

        mock_handler.assert_called_once()
