"""
Tests for entrypoints/gcp_cloudrun.py.
Mocks all cloud and AI calls — no real GCP, Vertex AI, or Slack interactions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_report(scan_id: str = "gcp-scan-id") -> dict:
    return {
        "scan_id": scan_id,
        "generated_at": "2026-06-17T00:00:00+00:00",
        "cloud": "gcp",
        "accounts_scanned": ["my-project"],
        "total_estimated_waste_usd": 200.0,
        "findings_count": 3,
        "findings": [],
        "executive_summary": "Three idle resources found.",
    }


def _make_mock_loop(findings=None, summary="No waste found."):
    """Return a MagicMock AgentLoop with sensible tracker defaults."""
    loop = MagicMock()
    loop.run.return_value = (findings or [], summary)
    loop.tracker.summary.return_value = {
        "total_input_tokens": 100,
        "total_output_tokens": 50,
    }
    loop.tracker.total_input_tokens = 100
    loop.tracker.total_output_tokens = 50
    return loop


# ---------------------------------------------------------------------------
# main — happy path (single project)
# ---------------------------------------------------------------------------


class TestMain:
    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
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
        monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop_cls.return_value = _make_mock_loop()
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()

        mock_adapter_cls.assert_called_once_with(project_id="my-project")
        mock_loop_cls.assert_called_once()
        mock_loop_cls.return_value.run.assert_called_once()
        mock_build_report.assert_called_once()
        mock_post.assert_called_once()

    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
    def test_main_passes_project_id_to_loop(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project-123")
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop_cls.return_value = _make_mock_loop(summary="Clean.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()

        run_kwargs = mock_loop_cls.return_value.run.call_args.kwargs
        assert run_kwargs["cloud"] == "gcp"
        assert run_kwargs["accounts"] == [
            {"id": "test-project-123", "name": "test-project-123"}
        ]

    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
    def test_no_gcs_upload_when_bucket_not_set(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("GCP_PROJECT_ID", "proj")
        monkeypatch.delenv("REPORT_GCS_BUCKET", raising=False)
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop_cls.return_value = _make_mock_loop(summary="Clean.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        with patch("entrypoints.gcp_cloudrun._save_reports_to_gcs") as mock_gcs:
            main()
            mock_gcs.assert_not_called()


# ---------------------------------------------------------------------------
# main — missing GCP_PROJECT_ID
# ---------------------------------------------------------------------------


class TestMainMissingProjectId:
    def test_exits_when_project_id_not_set(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)
        monkeypatch.delenv("ACCOUNTS_CONFIG", raising=False)

        from entrypoints.gcp_cloudrun import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# main — Slack delivery
# ---------------------------------------------------------------------------


class TestMainSlackFailure:
    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
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
        monkeypatch.setenv("GCP_PROJECT_ID", "proj")
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop_cls.return_value = _make_mock_loop(summary="Summary.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# Multi-project support
# ---------------------------------------------------------------------------


class TestMultiProject:
    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
    def test_multi_project_via_env_var(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("GCP_PROJECT_IDS", "proj-dev,proj-prod")
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop_cls.return_value = _make_mock_loop()
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()

        assert mock_adapter_cls.call_count == 2
        mock_adapter_cls.assert_any_call(project_id="proj-dev")
        mock_adapter_cls.assert_any_call(project_id="proj-prod")
        assert mock_loop_cls.return_value.run.call_count == 2

    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
    def test_multi_project_via_accounts_config(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv(
            "ACCOUNTS_CONFIG",
            json.dumps(
                [
                    {"id": "proj-alpha", "name": "alpha"},
                    {"id": "proj-beta", "name": "beta"},
                ]
            ),
        )
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)

        mock_loop_cls.return_value = _make_mock_loop()
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()

        assert mock_adapter_cls.call_count == 2
        mock_adapter_cls.assert_any_call(project_id="proj-alpha")
        mock_adapter_cls.assert_any_call(project_id="proj-beta")

    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
    def test_multi_project_uses_named_projects(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv(
            "ACCOUNTS_CONFIG",
            json.dumps([{"id": "proj-1", "name": "production"}]),
        )
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)

        mock_loop_cls.return_value = _make_mock_loop()
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()

        run_kwargs = mock_loop_cls.return_value.run.call_args.kwargs
        assert run_kwargs["accounts"] == [{"id": "proj-1", "name": "production"}]

    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
    def test_multi_project_skips_failing_project(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("GCP_PROJECT_IDS", "proj-ok,proj-fail")
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        call_count = 0

        def run_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise PermissionError("No access to proj-fail")
            return ([], "OK")

        mock_loop = _make_mock_loop()
        mock_loop.run.side_effect = run_side_effect
        mock_loop_cls.return_value = mock_loop
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()

        assert mock_loop.run.call_count == 2
        report_call = mock_build_report.call_args
        assert "proj-ok" in report_call.kwargs.get(
            "accounts_scanned", report_call[1].get("accounts_scanned", [])
        )
        # Failed project should be recorded in scan_errors, not silently dropped
        scan_errors = report_call.kwargs.get(
            "scan_errors", report_call[1].get("scan_errors", [])
        )
        assert len(scan_errors) == 1
        assert scan_errors[0]["account_id"] == "proj-fail"
        assert "No access" in scan_errors[0]["error"]

    @patch("entrypoints.gcp_cloudrun.notify_all")
    @patch("entrypoints.gcp_cloudrun.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.gcp_cloudrun.build_report")
    @patch("entrypoints.gcp_cloudrun.AgentLoop")
    @patch("entrypoints.gcp_cloudrun.GCPAdapter")
    @patch("entrypoints.gcp_cloudrun._build_ai_provider")
    def test_multi_project_aggregates_tokens(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("GCP_PROJECT_IDS", "proj-a,proj-b")
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        mock_loop = _make_mock_loop()
        mock_loop.tracker.total_input_tokens = 200
        mock_loop.tracker.total_output_tokens = 100
        mock_loop_cls.return_value = mock_loop
        mock_build_report.return_value = _fake_report()

        from entrypoints.gcp_cloudrun import main

        main()

        report_kwargs = mock_build_report.call_args.kwargs
        assert report_kwargs["agent_input_tokens"] == 400
        assert report_kwargs["agent_output_tokens"] == 200


# ---------------------------------------------------------------------------
# _get_project_ids
# ---------------------------------------------------------------------------


class TestGetProjectIds:
    def test_single_project_from_env(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "my-proj")
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        from entrypoints.gcp_cloudrun import _get_project_ids

        assert _get_project_ids() == ["my-proj"]

    def test_multi_project_from_env(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_IDS", "proj-a, proj-b, proj-c")
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        from entrypoints.gcp_cloudrun import _get_project_ids

        assert _get_project_ids() == ["proj-a", "proj-b", "proj-c"]

    def test_multi_project_ids_takes_priority(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_IDS", "proj-a,proj-b")
        monkeypatch.setenv("GCP_PROJECT_ID", "single-proj")
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)

        from entrypoints.gcp_cloudrun import _get_project_ids

        assert _get_project_ids() == ["proj-a", "proj-b"]

    def test_accounts_config_takes_priority(self, monkeypatch):
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv(
            "ACCOUNTS_CONFIG",
            json.dumps([{"id": "cfg-proj", "name": "from-config"}]),
        )
        monkeypatch.setenv("GCP_PROJECT_IDS", "env-proj")
        monkeypatch.setenv("GCP_PROJECT_ID", "single-proj")

        from entrypoints.gcp_cloudrun import _get_project_ids

        assert _get_project_ids() == ["cfg-proj"]

    def test_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("GCP_PROJECT_IDS", raising=False)
        monkeypatch.delenv("ACCOUNTS_MODE", raising=False)
        monkeypatch.delenv("ACCOUNTS_CONFIG", raising=False)

        from entrypoints.gcp_cloudrun import _get_project_ids

        assert _get_project_ids() == []


# ---------------------------------------------------------------------------
# _build_ai_provider
# ---------------------------------------------------------------------------


class TestBuildAIProvider:
    def test_default_returns_vertexai_provider(self, monkeypatch):
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.setenv("GCP_PROJECT_ID", "my-proj")

        with patch("ai.vertexai.VertexAIProvider") as mock_cls:
            from entrypoints.gcp_cloudrun import _build_ai_provider

            result = _build_ai_provider("my-proj")

        mock_cls.assert_called_once_with(project="my-proj", location="us-central1")
        assert result is mock_cls.return_value

    def test_vertexai_respects_env_overrides(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "vertexai")
        monkeypatch.setenv("VERTEXAI_PROJECT", "other-proj")
        monkeypatch.setenv("VERTEXAI_LOCATION", "europe-west1")

        with patch("ai.vertexai.VertexAIProvider") as mock_cls:
            from entrypoints.gcp_cloudrun import _build_ai_provider

            _build_ai_provider("fallback-proj")

        mock_cls.assert_called_once_with(project="other-proj", location="europe-west1")

    def test_anthropic_provider_when_set(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "anthropic")

        with patch("ai.anthropic.AnthropicProvider") as mock_cls:
            from entrypoints.gcp_cloudrun import _build_ai_provider

            result = _build_ai_provider("my-proj")

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value


# ---------------------------------------------------------------------------
# _save_reports_to_gcs
# ---------------------------------------------------------------------------


class TestSaveReportsToGCS:
    @patch("entrypoints.gcp_cloudrun.build_html_report", return_value="<html></html>")
    @patch(
        "entrypoints.gcp_cloudrun._generate_signed_url",
        return_value="https://storage.example.com/signed",
    )
    def test_uploads_json_and_html_and_returns_signed_url(
        self, mock_sign, mock_html, monkeypatch
    ):
        monkeypatch.setenv("REPORT_URL_EXPIRY", "3600")

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        mock_storage_mod = MagicMock()
        mock_storage_mod.Client.return_value = mock_client
        mock_google_cloud = MagicMock()
        mock_google_cloud.storage = mock_storage_mod

        with patch.dict(
            "sys.modules",
            {
                "google.cloud": mock_google_cloud,
                "google.cloud.storage": mock_storage_mod,
                "google.api_core": MagicMock(),
                "google.api_core.exceptions": MagicMock(),
            },
        ):
            from entrypoints.gcp_cloudrun import _save_reports_to_gcs

            url = _save_reports_to_gcs(_fake_report(), "my-gcs-bucket")

        assert mock_bucket.blob.call_count == 2
        assert mock_blob.upload_from_string.call_count == 2
        assert mock_sign.call_count == 1
        assert url == "https://storage.example.com/signed"

    def test_returns_none_when_storage_not_installed(self):
        """Verify graceful handling when google-cloud-storage is not available."""
        import sys

        # Temporarily remove google.cloud.storage if present
        modules_to_hide = [
            k for k in sys.modules if k.startswith("google.cloud.storage")
        ]
        saved = {k: sys.modules.pop(k) for k in modules_to_hide}

        try:
            with patch.dict(
                "sys.modules",
                {"google.cloud.storage": None, "google.cloud": None},
            ):
                # Force re-import to hit the ImportError path
                import entrypoints.gcp_cloudrun as mod

                # Call the function which tries to import google.cloud.storage inside
                result = mod._save_reports_to_gcs(_fake_report(), "bucket")

            assert result is None
        finally:
            sys.modules.update(saved)

    @patch("entrypoints.gcp_cloudrun.build_html_report", return_value="<html></html>")
    def test_returns_none_on_gcs_api_error(self, mock_html, monkeypatch):
        monkeypatch.setenv("REPORT_URL_EXPIRY", "3600")

        mock_google_exc = MagicMock()
        exc_class = type("GoogleAPIError", (Exception,), {})
        actual_exc = exc_class("GCS permission denied")
        mock_google_exc.GoogleAPIError = exc_class

        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.upload_from_string.side_effect = actual_exc

        mock_storage = MagicMock()
        mock_storage.Client.return_value = mock_client

        mock_google_api_core = MagicMock()
        mock_google_api_core.exceptions = mock_google_exc
        mock_google_cloud = MagicMock()
        mock_google_cloud.storage = mock_storage

        with patch.dict(
            "sys.modules",
            {
                "google.cloud": mock_google_cloud,
                "google.cloud.storage": mock_storage,
                "google.api_core": mock_google_api_core,
                "google.api_core.exceptions": mock_google_exc,
            },
        ):
            from entrypoints.gcp_cloudrun import _save_reports_to_gcs

            result = _save_reports_to_gcs(_fake_report(), "bad-bucket")

        assert result is None
