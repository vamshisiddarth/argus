"""
Tests for entrypoints/azure_function.py.
Mocks all cloud and AI calls — no real Azure, OpenAI, or Slack interactions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_report(scan_id: str = "azure-scan-id") -> dict:
    return {
        "scan_id": scan_id,
        "generated_at": "2026-06-17T00:00:00+00:00",
        "cloud": "azure",
        "accounts_scanned": ["sub-111", "sub-222"],
        "total_estimated_waste_usd": 320.0,
        "findings_count": 4,
        "findings": [],
        "executive_summary": "Four idle resources found.",
    }


def _mock_timer(past_due: bool = False) -> MagicMock:
    timer = MagicMock()
    timer.past_due = past_due
    return timer


# ---------------------------------------------------------------------------
# main — happy path
# ---------------------------------------------------------------------------


class TestMain:
    @patch("entrypoints.azure_function.notify_all")
    @patch(
        "entrypoints.azure_function.build_slack_payload", return_value={"blocks": []}
    )
    @patch("entrypoints.azure_function.build_report")
    @patch("entrypoints.azure_function.AgentLoop")
    @patch("entrypoints.azure_function.AzureAdapter")
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_main_runs_scan_and_posts_to_slack(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-111,sub-222")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop_cls.return_value.run.return_value = ([], "No waste found.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.azure_function import main

        main(_mock_timer())

        mock_adapter_cls.assert_called_once_with(
            subscription_ids=["sub-111", "sub-222"]
        )
        mock_loop_cls.assert_called_once()
        mock_loop_cls.return_value.run.assert_called_once()
        mock_build_report.assert_called_once()
        mock_post.assert_called_once()

    @patch("entrypoints.azure_function.notify_all")
    @patch(
        "entrypoints.azure_function.build_slack_payload", return_value={"blocks": []}
    )
    @patch("entrypoints.azure_function.build_report")
    @patch("entrypoints.azure_function.AgentLoop")
    @patch("entrypoints.azure_function.AzureAdapter")
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_main_passes_subscription_ids_to_loop(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-aaa, sub-bbb")
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop_cls.return_value.run.return_value = ([], "Clean.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.azure_function import main

        main(_mock_timer())

        mock_adapter_cls.assert_called_once_with(
            subscription_ids=["sub-aaa", "sub-bbb"]
        )
        run_kwargs = mock_loop_cls.return_value.run.call_args.kwargs
        assert run_kwargs["cloud"] == "azure"
        assert run_kwargs["accounts"] == [
            {"id": "sub-aaa", "name": "sub-aaa"},
            {"id": "sub-bbb", "name": "sub-bbb"},
        ]

    @patch("entrypoints.azure_function.notify_all")
    @patch(
        "entrypoints.azure_function.build_slack_payload", return_value={"blocks": []}
    )
    @patch("entrypoints.azure_function.build_report")
    @patch("entrypoints.azure_function.AgentLoop")
    @patch("entrypoints.azure_function.AzureAdapter")
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_no_blob_upload_when_storage_account_not_set(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-111")
        monkeypatch.delenv("REPORT_STORAGE_ACCOUNT", raising=False)

        mock_loop_cls.return_value.run.return_value = ([], "Clean.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.azure_function import main

        with patch("entrypoints.azure_function._save_reports_to_blob") as mock_blob:
            main(_mock_timer())
            mock_blob.assert_not_called()


# ---------------------------------------------------------------------------
# main — missing AZURE_SUBSCRIPTION_IDS
# ---------------------------------------------------------------------------


class TestMainMissingSubscriptionIds:
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_returns_early_when_subscription_ids_not_set(self, mock_ai, monkeypatch):
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)
        monkeypatch.delenv("ACCOUNTS_CONFIG", raising=False)

        from entrypoints.azure_function import main

        main(_mock_timer())

        mock_ai.assert_not_called()


# ---------------------------------------------------------------------------
# main — past_due timer
# ---------------------------------------------------------------------------


class TestMainPastDueTimer:
    @patch("entrypoints.azure_function.notify_all")
    @patch(
        "entrypoints.azure_function.build_slack_payload", return_value={"blocks": []}
    )
    @patch("entrypoints.azure_function.build_report")
    @patch("entrypoints.azure_function.AgentLoop")
    @patch("entrypoints.azure_function.AzureAdapter")
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_past_due_timer_logs_warning_but_continues(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
        caplog,
    ):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-111")

        mock_loop_cls.return_value.run.return_value = ([], "Summary.")
        mock_build_report.return_value = _fake_report()

        import logging

        from entrypoints.azure_function import main

        with caplog.at_level(logging.WARNING):
            main(_mock_timer(past_due=True))

        assert "past due" in caplog.text.lower()
        # Scan still runs
        mock_loop_cls.return_value.run.assert_called_once()


# ---------------------------------------------------------------------------
# main — Slack delivery failure
# ---------------------------------------------------------------------------


class TestMainSlackFailure:
    @patch("entrypoints.azure_function.notify_all")
    @patch(
        "entrypoints.azure_function.build_slack_payload", return_value={"blocks": []}
    )
    @patch("entrypoints.azure_function.build_report")
    @patch("entrypoints.azure_function.AgentLoop")
    @patch("entrypoints.azure_function.AzureAdapter")
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_notify_all_is_called(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-111")

        mock_loop_cls.return_value.run.return_value = ([], "Summary.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.azure_function import main

        main(_mock_timer())
        mock_post.assert_called_once()

    @patch("entrypoints.azure_function.notify_all", return_value=False)
    @patch(
        "entrypoints.azure_function.build_slack_payload", return_value={"blocks": []}
    )
    @patch("entrypoints.azure_function.build_report")
    @patch("entrypoints.azure_function.AgentLoop")
    @patch("entrypoints.azure_function.AzureAdapter")
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_exits_1_when_all_providers_fail(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-111")

        mock_loop_cls.return_value.run.return_value = ([], "Summary.")
        mock_build_report.return_value = _fake_report()

        import pytest

        from entrypoints.azure_function import main

        with pytest.raises(SystemExit) as exc_info:
            main(_mock_timer())
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _build_ai_provider
# ---------------------------------------------------------------------------


class TestBuildAIProvider:
    def test_default_returns_azure_openai_provider(self, monkeypatch):
        monkeypatch.delenv("AI_PROVIDER", raising=False)

        with patch("ai.azure_openai.AzureOpenAIProvider") as mock_cls:
            from entrypoints.azure_function import _build_ai_provider

            result = _build_ai_provider()

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value

    def test_explicit_azure_openai(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "azure_openai")

        with patch("ai.azure_openai.AzureOpenAIProvider") as mock_cls:
            from entrypoints.azure_function import _build_ai_provider

            result = _build_ai_provider()

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value

    def test_anthropic_provider_when_set(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "anthropic")

        with patch("ai.anthropic.AnthropicProvider") as mock_cls:
            from entrypoints.azure_function import _build_ai_provider

            result = _build_ai_provider()

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value


# ---------------------------------------------------------------------------
# _save_reports_to_blob
# ---------------------------------------------------------------------------


class TestSaveReportsToBlob:
    @patch("entrypoints.azure_function.build_html_report", return_value="<html></html>")
    def test_uploads_json_and_html_and_returns_sas_url(self, mock_html, monkeypatch):
        monkeypatch.setenv("REPORT_STORAGE_CONTAINER", "my-container")
        monkeypatch.setenv("REPORT_URL_EXPIRY", "3600")

        mock_container_client = MagicMock()
        mock_blob_service = MagicMock()
        mock_blob_service.get_container_client.return_value = mock_container_client
        mock_blob_service.get_user_delegation_key.return_value = MagicMock()

        mock_credential = MagicMock()
        mock_generate_sas = MagicMock(return_value="sas-token-here")
        mock_sas_permissions = MagicMock()

        # Build mock modules
        mock_blob_mod = MagicMock()
        mock_blob_mod.BlobServiceClient.return_value = mock_blob_service
        mock_blob_mod.generate_blob_sas = mock_generate_sas
        mock_blob_mod.BlobSasPermissions.return_value = mock_sas_permissions

        mock_identity_mod = MagicMock()
        mock_identity_mod.DefaultAzureCredential.return_value = mock_credential

        mock_core_exc = MagicMock()
        # Create real exception classes so isinstance checks work
        azure_error_cls = type("AzureError", (Exception,), {})
        resource_exists_cls = type("ResourceExistsError", (azure_error_cls,), {})
        mock_core_exc.AzureError = azure_error_cls
        mock_core_exc.ResourceExistsError = resource_exists_cls

        with patch.dict(
            "sys.modules",
            {
                "azure.storage.blob": mock_blob_mod,
                "azure.identity": mock_identity_mod,
                "azure.core.exceptions": mock_core_exc,
                "azure.core": MagicMock(),
                "azure.storage": MagicMock(),
                "azure": MagicMock(),
            },
        ):
            from entrypoints.azure_function import _save_reports_to_blob

            url = _save_reports_to_blob(_fake_report(), "mystorageaccount")

        assert mock_container_client.upload_blob.call_count == 2
        assert mock_generate_sas.call_count == 1
        assert url is not None
        assert "mystorageaccount" in url
        assert "sas-token-here" in url

    def test_returns_none_when_storage_not_installed(self):
        """Verify graceful handling when azure-storage-blob is not available."""
        import sys

        modules_to_hide = [
            k
            for k in sys.modules
            if k.startswith("azure.storage.blob") or k.startswith("azure.identity")
        ]
        saved = {k: sys.modules.pop(k) for k in modules_to_hide}

        try:
            with patch.dict(
                "sys.modules",
                {
                    "azure.storage.blob": None,
                    "azure.identity": None,
                    "azure.core.exceptions": None,
                },
            ):
                import entrypoints.azure_function as mod

                result = mod._save_reports_to_blob(_fake_report(), "account")

            assert result is None
        finally:
            sys.modules.update(saved)

    @patch("entrypoints.azure_function.build_html_report", return_value="<html></html>")
    def test_returns_none_on_azure_error(self, mock_html, monkeypatch):
        monkeypatch.setenv("REPORT_STORAGE_CONTAINER", "my-container")
        monkeypatch.setenv("REPORT_URL_EXPIRY", "3600")

        azure_error_cls = type("AzureError", (Exception,), {})
        resource_exists_cls = type("ResourceExistsError", (azure_error_cls,), {})

        mock_container_client = MagicMock()
        mock_container_client.upload_blob.side_effect = azure_error_cls("access denied")

        mock_blob_service = MagicMock()
        mock_blob_service.get_container_client.return_value = mock_container_client

        mock_blob_mod = MagicMock()
        mock_blob_mod.BlobServiceClient.return_value = mock_blob_service
        mock_blob_mod.BlobSasPermissions.return_value = MagicMock()

        mock_identity_mod = MagicMock()
        mock_identity_mod.DefaultAzureCredential.return_value = MagicMock()

        mock_core_exc = MagicMock()
        mock_core_exc.AzureError = azure_error_cls
        mock_core_exc.ResourceExistsError = resource_exists_cls

        with patch.dict(
            "sys.modules",
            {
                "azure.storage.blob": mock_blob_mod,
                "azure.identity": mock_identity_mod,
                "azure.core.exceptions": mock_core_exc,
                "azure.core": MagicMock(),
                "azure.storage": MagicMock(),
                "azure": MagicMock(),
            },
        ):
            from entrypoints.azure_function import _save_reports_to_blob

            result = _save_reports_to_blob(_fake_report(), "bad-account")

        assert result is None

    @patch("entrypoints.azure_function.build_html_report", return_value="<html></html>")
    def test_container_already_exists_does_not_fail(  # noqa: E501
        self, mock_html, monkeypatch
    ):
        monkeypatch.setenv("REPORT_STORAGE_CONTAINER", "existing-container")
        monkeypatch.setenv("REPORT_URL_EXPIRY", "3600")

        azure_error_cls = type("AzureError", (Exception,), {})
        resource_exists_cls = type("ResourceExistsError", (azure_error_cls,), {})

        mock_container_client = MagicMock()
        mock_container_client.create_container.side_effect = resource_exists_cls(
            "already exists"
        )

        mock_blob_service = MagicMock()
        mock_blob_service.get_container_client.return_value = mock_container_client
        mock_blob_service.get_user_delegation_key.return_value = MagicMock()

        mock_blob_mod = MagicMock()
        mock_blob_mod.BlobServiceClient.return_value = mock_blob_service
        mock_blob_mod.generate_blob_sas.return_value = "sas-token"
        mock_blob_mod.BlobSasPermissions.return_value = MagicMock()

        mock_identity_mod = MagicMock()
        mock_identity_mod.DefaultAzureCredential.return_value = MagicMock()

        mock_core_exc = MagicMock()
        mock_core_exc.AzureError = azure_error_cls
        mock_core_exc.ResourceExistsError = resource_exists_cls

        with patch.dict(
            "sys.modules",
            {
                "azure.storage.blob": mock_blob_mod,
                "azure.identity": mock_identity_mod,
                "azure.core.exceptions": mock_core_exc,
                "azure.core": MagicMock(),
                "azure.storage": MagicMock(),
                "azure": MagicMock(),
            },
        ):
            from entrypoints.azure_function import _save_reports_to_blob

            url = _save_reports_to_blob(_fake_report(), "mystorageaccount")

        # Should succeed despite ResourceExistsError on create_container
        assert url is not None
        assert mock_container_client.upload_blob.call_count == 2


# ---------------------------------------------------------------------------
# _get_subscription_ids — multi-subscription resolution
# ---------------------------------------------------------------------------


class TestGetSubscriptionIds:
    def test_reads_from_env_var(self, monkeypatch):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-1, sub-2")
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        from entrypoints.azure_function import _get_subscription_ids

        ids, names = _get_subscription_ids()
        assert ids == ["sub-1", "sub-2"]
        assert names == {}

    def test_reads_from_accounts_config(self, monkeypatch):
        import json

        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv(
            "ACCOUNTS_CONFIG",
            json.dumps(
                [
                    {"id": "sub-aaa", "name": "dev"},
                    {"id": "sub-bbb", "name": "prod"},
                ]
            ),
        )
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)

        from entrypoints.azure_function import _get_subscription_ids

        ids, names = _get_subscription_ids()
        assert ids == ["sub-aaa", "sub-bbb"]
        assert names == {"sub-aaa": "dev", "sub-bbb": "prod"}

    def test_accounts_config_takes_priority(self, monkeypatch):
        import json

        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv(
            "ACCOUNTS_CONFIG",
            json.dumps([{"id": "cfg-sub", "name": "from-config"}]),
        )
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "env-sub")

        from entrypoints.azure_function import _get_subscription_ids

        ids, _ = _get_subscription_ids()
        assert ids == ["cfg-sub"]

    def test_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)
        monkeypatch.delenv("ACCOUNTS_CONFIG", raising=False)

        from entrypoints.azure_function import _get_subscription_ids

        ids, names = _get_subscription_ids()
        assert ids == []
        assert names == {}


class TestMultiSubscriptionIntegration:
    @patch("entrypoints.azure_function.notify_all")
    @patch(
        "entrypoints.azure_function.build_slack_payload", return_value={"blocks": []}
    )
    @patch("entrypoints.azure_function.build_report")
    @patch("entrypoints.azure_function.AgentLoop")
    @patch("entrypoints.azure_function.AzureAdapter")
    @patch("entrypoints.azure_function._build_ai_provider")
    def test_named_subscriptions_from_config(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        import json

        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv(
            "ACCOUNTS_CONFIG",
            json.dumps(
                [
                    {"id": "sub-aaa", "name": "development"},
                    {"id": "sub-bbb", "name": "production"},
                ]
            ),
        )
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)

        mock_loop_cls.return_value.run.return_value = ([], "Clean.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.azure_function import main

        main(_mock_timer())

        mock_adapter_cls.assert_called_once_with(
            subscription_ids=["sub-aaa", "sub-bbb"]
        )
        run_kwargs = mock_loop_cls.return_value.run.call_args.kwargs
        assert run_kwargs["accounts"] == [
            {"id": "sub-aaa", "name": "development"},
            {"id": "sub-bbb", "name": "production"},
        ]
