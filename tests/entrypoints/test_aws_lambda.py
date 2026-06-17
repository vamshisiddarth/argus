"""
Tests for entrypoints/aws_lambda.py.
Mocks all cloud and AI calls — no real AWS, Bedrock, or Slack interactions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.reports.delivery import SlackDeliveryError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_report(scan_id: str = "test-scan-id") -> dict:
    return {
        "scan_id": scan_id,
        "generated_at": "2026-06-17T00:00:00+00:00",
        "cloud": "aws",
        "accounts_scanned": ["123456789012"],
        "total_estimated_waste_usd": 150.0,
        "findings_count": 2,
        "findings": [],
        "executive_summary": "Two idle instances found.",
    }


# ---------------------------------------------------------------------------
# handler — single-account mode
# ---------------------------------------------------------------------------


class TestHandlerSingleAccount:
    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch(
        "entrypoints.aws_lambda._get_current_account_id", return_value="123456789012"
    )
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_returns_200_with_scan_results(
        self,
        mock_ai,
        mock_acct_id,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "single")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        mock_loop_cls.return_value.run.return_value = ([], "No waste found.")
        report = _fake_report()
        mock_build_report.return_value = report

        from entrypoints.aws_lambda import handler

        result = handler({}, None)

        assert result["statusCode"] == 200
        assert result["scan_id"] == "test-scan-id"
        assert result["findings_count"] == 2
        assert result["total_estimated_waste_usd"] == 150.0

    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch(
        "entrypoints.aws_lambda._get_current_account_id", return_value="123456789012"
    )
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_calls_adapter_for_account_and_loop_run(
        self,
        mock_ai,
        mock_acct_id,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "single")
        monkeypatch.setenv("PRIMARY_REGION", "eu-west-1")

        mock_loop_cls.return_value.run.return_value = ([], "Clean.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.aws_lambda import handler

        handler({}, None)

        mock_adapter_cls.for_account.assert_called_once_with(
            account=None, region="eu-west-1"
        )
        mock_loop_cls.return_value.run.assert_called_once()

    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch(
        "entrypoints.aws_lambda._get_current_account_id", return_value="123456789012"
    )
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_no_s3_upload_when_bucket_not_set(
        self,
        mock_ai,
        mock_acct_id,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.delenv("REPORT_S3_BUCKET", raising=False)
        monkeypatch.setenv("ACCOUNTS_MODE", "single")

        mock_loop_cls.return_value.run.return_value = ([], "Clean.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.aws_lambda import handler

        with patch("entrypoints.aws_lambda._save_reports_to_s3") as mock_s3:
            handler({}, None)
            mock_s3.assert_not_called()


# ---------------------------------------------------------------------------
# handler — multi-account mode
# ---------------------------------------------------------------------------


class TestHandlerMultiAccount:
    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_multi_account_loops_over_accounts(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        accounts = [
            {"id": "111", "name": "dev", "role_arn": "arn:aws:iam::111:role/R"},
            {"id": "222", "name": "prod", "role_arn": "arn:aws:iam::222:role/R"},
        ]
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv("ACCOUNTS_CONFIG", json.dumps(accounts))

        mock_loop_cls.return_value.run.return_value = ([], "Nothing idle.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.aws_lambda import handler

        handler({}, None)

        assert mock_adapter_cls.for_account.call_count == 2
        assert mock_loop_cls.return_value.run.call_count == 2

    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_multi_account_build_report_gets_all_account_ids(
        self,
        mock_ai,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        accounts = [
            {"id": "111", "name": "dev", "role_arn": "arn:aws:iam::111:role/R"},
            {"id": "222", "name": "prod", "role_arn": "arn:aws:iam::222:role/R"},
        ]
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv("ACCOUNTS_CONFIG", json.dumps(accounts))

        mock_loop_cls.return_value.run.return_value = ([], "Nothing.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.aws_lambda import handler

        handler({}, None)

        call_kwargs = mock_build_report.call_args
        assert call_kwargs.kwargs["accounts_scanned"] == ["111", "222"]

    def test_invalid_accounts_config_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv("ACCOUNTS_CONFIG", "not valid json{{{")

        with patch("entrypoints.aws_lambda._build_ai_provider"):
            from entrypoints.aws_lambda import handler

            with pytest.raises(ValueError, match="ACCOUNTS_CONFIG is not valid JSON"):
                handler({}, None)

    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch("entrypoints.aws_lambda._get_current_account_id", return_value="fallback-id")
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_multi_account_empty_config_falls_back_to_single(
        self,
        mock_ai,
        mock_acct_id,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv("ACCOUNTS_CONFIG", "[]")

        mock_loop_cls.return_value.run.return_value = ([], "Fallback.")
        mock_build_report.return_value = _fake_report()

        from entrypoints.aws_lambda import handler

        handler({}, None)

        # Falls back to single-account, so for_account gets account=None
        mock_adapter_cls.for_account.assert_called_once_with(
            account=None, region="us-east-1"
        )


# ---------------------------------------------------------------------------
# _build_ai_provider
# ---------------------------------------------------------------------------


class TestBuildAIProvider:
    def test_default_returns_bedrock_provider(self, monkeypatch):
        monkeypatch.delenv("AI_PROVIDER", raising=False)

        with patch("ai.bedrock.BedrockProvider") as mock_cls:
            from entrypoints.aws_lambda import _build_ai_provider

            result = _build_ai_provider()

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value

    def test_anthropic_provider_when_set(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "anthropic")

        with patch("ai.anthropic.AnthropicProvider") as mock_cls:
            from entrypoints.aws_lambda import _build_ai_provider

            result = _build_ai_provider()

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value

    def test_bedrock_explicit(self, monkeypatch):
        monkeypatch.setenv("AI_PROVIDER", "bedrock")

        with patch("ai.bedrock.BedrockProvider") as mock_cls:
            from entrypoints.aws_lambda import _build_ai_provider

            result = _build_ai_provider()

        mock_cls.assert_called_once()
        assert result is mock_cls.return_value


# ---------------------------------------------------------------------------
# _save_reports_to_s3
# ---------------------------------------------------------------------------


class TestSaveReportsToS3:
    @patch("entrypoints.aws_lambda.build_html_report", return_value="<html></html>")
    @patch("entrypoints.aws_lambda.boto3")
    def test_uploads_json_and_html(self, mock_boto3, mock_html, monkeypatch):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.generate_presigned_url.return_value = (
            "https://s3.example.com/report.html"
        )
        monkeypatch.setenv("REPORT_URL_EXPIRY", "3600")

        from entrypoints.aws_lambda import _save_reports_to_s3

        report = _fake_report()
        url = _save_reports_to_s3(report, "my-bucket")

        assert mock_s3.put_object.call_count == 2

        # First call: JSON report
        json_call = mock_s3.put_object.call_args_list[0]
        assert json_call.kwargs["Bucket"] == "my-bucket"
        assert json_call.kwargs["ContentType"] == "application/json"
        assert json_call.kwargs["Key"].endswith(".json")

        # Second call: HTML report
        html_call = mock_s3.put_object.call_args_list[1]
        assert html_call.kwargs["Bucket"] == "my-bucket"
        assert html_call.kwargs["ContentType"] == "text/html; charset=utf-8"
        assert html_call.kwargs["Key"].endswith(".html")

        assert url == "https://s3.example.com/report.html"

    @patch("entrypoints.aws_lambda.build_html_report", return_value="<html></html>")
    @patch("entrypoints.aws_lambda.boto3")
    def test_generates_presigned_url(self, mock_boto3, mock_html, monkeypatch):
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.generate_presigned_url.return_value = "https://presigned.example.com"
        monkeypatch.setenv("REPORT_URL_EXPIRY", "7200")

        from entrypoints.aws_lambda import _save_reports_to_s3

        _save_reports_to_s3(_fake_report(), "bucket")

        mock_s3.generate_presigned_url.assert_called_once()
        call_kwargs = mock_s3.generate_presigned_url.call_args
        assert call_kwargs.args[0] == "get_object"
        assert call_kwargs.kwargs["ExpiresIn"] == 7200

    @patch("entrypoints.aws_lambda.boto3")
    def test_returns_none_on_client_error(self, mock_boto3):
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
            "PutObject",
        )

        from entrypoints.aws_lambda import _save_reports_to_s3

        result = _save_reports_to_s3(_fake_report(), "bad-bucket")

        assert result is None


# ---------------------------------------------------------------------------
# handler — Slack delivery failure
# ---------------------------------------------------------------------------


class TestHandlerSlackFailure:
    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch(
        "entrypoints.aws_lambda._get_current_account_id", return_value="123456789012"
    )
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_slack_failure_does_not_crash_handler(
        self,
        mock_ai,
        mock_acct_id,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "single")

        mock_loop_cls.return_value.run.return_value = ([], "Summary.")
        mock_build_report.return_value = _fake_report()
        mock_post.side_effect = SlackDeliveryError("webhook 400")

        from entrypoints.aws_lambda import handler

        result = handler({}, None)

        assert result["statusCode"] == 200

    @patch("entrypoints.aws_lambda.post_to_slack")
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch(
        "entrypoints.aws_lambda._get_current_account_id", return_value="123456789012"
    )
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_os_error_during_slack_does_not_crash(
        self,
        mock_ai,
        mock_acct_id,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_post,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "single")

        mock_loop_cls.return_value.run.return_value = ([], "Summary.")
        mock_build_report.return_value = _fake_report()
        mock_post.side_effect = OSError("Connection reset")

        from entrypoints.aws_lambda import handler

        result = handler({}, None)

        assert result["statusCode"] == 200


# ---------------------------------------------------------------------------
# _get_current_account_id
# ---------------------------------------------------------------------------


class TestGetCurrentAccountId:
    @patch("entrypoints.aws_lambda.boto3")
    def test_returns_account_id_from_sts(self, mock_boto3):
        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.get_caller_identity.return_value = {"Account": "999888777666"}

        from entrypoints.aws_lambda import _get_current_account_id

        assert _get_current_account_id() == "999888777666"

    @patch("entrypoints.aws_lambda.boto3")
    def test_returns_unknown_on_sts_error(self, mock_boto3):
        from botocore.exceptions import ClientError

        mock_sts = MagicMock()
        mock_boto3.client.return_value = mock_sts
        mock_sts.get_caller_identity.side_effect = ClientError(
            {"Error": {"Code": "ExpiredToken", "Message": "Token expired"}},
            "GetCallerIdentity",
        )

        from entrypoints.aws_lambda import _get_current_account_id

        assert _get_current_account_id() == "unknown"
