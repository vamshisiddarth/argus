"""
Tests for entrypoints/aws_lambda.py.
Mocks all cloud and AI calls — no real AWS, Bedrock, or Slack interactions.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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
    @patch("entrypoints.aws_lambda.notify_all")
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

    @patch("entrypoints.aws_lambda.notify_all")
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

    @patch("entrypoints.aws_lambda.notify_all")
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
    @patch("entrypoints.aws_lambda.notify_all")
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

    @patch("entrypoints.aws_lambda.notify_all")
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

    def test_invalid_accounts_config_returns_500(self, monkeypatch):
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv("ACCOUNTS_CONFIG", "not valid json{{{")

        from entrypoints.aws_lambda import handler

        result = handler({}, None)
        assert result["statusCode"] == 500
        assert "ACCOUNTS_CONFIG" in result["error"]

    def test_multi_account_empty_config_returns_500(self, monkeypatch):
        """Empty ACCOUNTS_CONFIG is a misconfiguration — fail fast at startup."""
        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv("ACCOUNTS_CONFIG", "[]")

        from entrypoints.aws_lambda import handler

        result = handler({}, None)
        assert result["statusCode"] == 500
        assert "non-empty" in result["error"]


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
    @patch("entrypoints.aws_lambda.notify_all")
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
        from entrypoints.aws_lambda import handler

        result = handler({}, None)

        assert result["statusCode"] == 200
        mock_post.assert_called_once()


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


# ---------------------------------------------------------------------------
# handler — notify_all returns False → Lambda must raise so CloudWatch fires
# ---------------------------------------------------------------------------


class TestHandlerSlackDeliveryFailureRaises:
    @patch("entrypoints.aws_lambda.notify_all", return_value=False)
    @patch("entrypoints.aws_lambda.build_slack_payload", return_value={"blocks": []})
    @patch("entrypoints.aws_lambda.build_report")
    @patch("entrypoints.aws_lambda.AgentLoop")
    @patch("entrypoints.aws_lambda.AWSAdapter")
    @patch(
        "entrypoints.aws_lambda._get_current_account_id", return_value="123456789012"
    )
    @patch("entrypoints.aws_lambda._build_ai_provider")
    def test_raises_when_all_providers_fail(
        self,
        mock_ai,
        mock_acct_id,
        mock_adapter_cls,
        mock_loop_cls,
        mock_build_report,
        mock_build_payload,
        mock_notify,
        monkeypatch,
    ):
        monkeypatch.setenv("ACCOUNTS_MODE", "single")
        mock_loop_cls.return_value.run.return_value = ([], "Summary.")
        mock_build_report.return_value = _fake_report()

        import pytest

        from entrypoints.aws_lambda import handler

        with pytest.raises(RuntimeError, match="Slack delivery failed"):
            handler({}, None)


class TestHandlerCoverage:
    def _run(self, monkeypatch, strict: bool, coverage):
        from unittest.mock import patch

        monkeypatch.setenv("ACCOUNTS_MODE", "single")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        if strict:
            monkeypatch.setenv("STRICT_COVERAGE", "true")
        with (
            patch("entrypoints.aws_lambda.notify_all"),
            patch("entrypoints.aws_lambda.build_slack_payload", return_value={"b": []}),
            patch(
                "entrypoints.aws_lambda.build_report", return_value=_fake_report()
            ) as mock_build,
            patch("entrypoints.aws_lambda.AgentLoop") as mock_loop_cls,
            patch("entrypoints.aws_lambda.AWSAdapter"),
            patch(
                "entrypoints.aws_lambda._get_current_account_id",
                return_value="123456789012",
            ),
            patch("entrypoints.aws_lambda._build_ai_provider"),
        ):
            loop = mock_loop_cls.return_value
            loop.run.return_value = ([], "ok")
            loop.coverage = coverage
            from entrypoints.aws_lambda import handler

            result = handler({}, None)
        return result, mock_build

    def _truncated(self):
        from core.models.coverage import Coverage, TypeCoverage

        return Coverage(
            880, 200, "cost_desc", True, ["us-east-1"], {"T": TypeCoverage(880, 200)}
        )

    def test_coverage_passed_to_report_and_result(self, monkeypatch):
        result, mock_build = self._run(monkeypatch, False, self._truncated())

        assert mock_build.call_args.kwargs["coverage"]["dropped"] == 680
        assert result["coverage"]["truncated"] is True

    def test_strict_coverage_fails_when_truncated(self, monkeypatch):
        import pytest

        from core.errors import StrictCoverageError

        with pytest.raises(StrictCoverageError):
            self._run(monkeypatch, True, self._truncated())


class TestHandlerPreflight:
    def _result(self, status="fail", account="123456789012"):
        from core.models.preflight import PreflightCheck, PreflightResult

        return PreflightResult(
            account_id=account,
            checks=[
                PreflightCheck(
                    "P3_AGGREGATOR_INDEX", status, "no aggregator index", "create one"
                )
            ],
        )

    def _patches(self):
        from unittest.mock import patch

        return (
            patch("entrypoints.aws_lambda.notify_all"),
            patch("entrypoints.aws_lambda.build_slack_payload", return_value={"b": []}),
            patch("entrypoints.aws_lambda.build_report", return_value=_fake_report()),
            patch("entrypoints.aws_lambda.AgentLoop"),
            patch("entrypoints.aws_lambda.AWSAdapter"),
            patch(
                "entrypoints.aws_lambda._get_current_account_id",
                return_value="123456789012",
            ),
            patch("entrypoints.aws_lambda._build_ai_provider"),
        )

    def _run(self, monkeypatch, mode, adapter_setup, accounts=None, skip=False):
        from contextlib import ExitStack

        monkeypatch.setenv("ARGUS_SKIP_PREFLIGHT", "true" if skip else "false")
        monkeypatch.setenv("ACCOUNTS_MODE", mode)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        if accounts:
            monkeypatch.setenv("ACCOUNTS_CONFIG", json.dumps(accounts))
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in self._patches()]
            _, _, mock_build, mock_loop_cls, mock_adapter_cls, _, _ = mocks
            adapter_setup(mock_adapter_cls)
            mock_loop_cls.return_value.run.return_value = ([], "ok")
            from entrypoints.aws_lambda import handler

            try:
                result = handler({}, None)
            except Exception as exc:  # noqa: BLE001
                return exc, mock_loop_cls, mock_build
            return result, mock_loop_cls, mock_build

    def test_preflight_failure_raises_and_makes_no_ai_calls(self, monkeypatch):
        from core.errors import PreflightFailedError

        def setup(adapter_cls):
            adapter_cls.for_account.return_value.preflight.return_value = self._result()

        exc, loop_cls, _ = self._run(monkeypatch, "single", setup)

        assert isinstance(exc, PreflightFailedError)
        assert "no aggregator index" in str(exc)
        assert "create one" in str(exc)
        loop_cls.return_value.run.assert_not_called()

    def test_preflight_warning_continues_and_is_in_report(self, monkeypatch):
        def setup(adapter_cls):
            adapter_cls.for_account.return_value.preflight.return_value = self._result(
                "warn"
            )

        result, loop_cls, mock_build = self._run(monkeypatch, "single", setup)

        assert result["statusCode"] == 200
        loop_cls.return_value.run.assert_called_once()
        pre = mock_build.call_args.kwargs["preflight"]
        assert pre["skipped"] is False
        assert pre["accounts"][0]["checks"][0]["status"] == "warn"
        assert result["preflight"]["warnings"] == [
            "P3_AGGREGATOR_INDEX: no aggregator index"
        ]

    def test_skip_preflight_sets_flag_in_report(self, monkeypatch):
        adapter = MagicMock()

        def setup(adapter_cls):
            adapter_cls.for_account.return_value = adapter

        result, loop_cls, mock_build = self._run(
            monkeypatch, "single", setup, skip=True
        )

        assert result["statusCode"] == 200
        adapter.preflight.assert_not_called()
        assert mock_build.call_args.kwargs["preflight"]["skipped"] is True
        assert result["preflight"]["skipped"] is True

    def test_multi_account_one_preflight_failure_others_continue(self, monkeypatch):
        accounts = [
            {
                "id": "111111111111",
                "name": "bad",
                "role_arn": "arn:aws:iam::111111111111:role/r",
            },
            {
                "id": "222222222222",
                "name": "good",
                "role_arn": "arn:aws:iam::222222222222:role/r",
            },
        ]

        def setup(adapter_cls):
            bad = MagicMock()
            bad.preflight.return_value = self._result("fail", "111111111111")
            good = MagicMock()
            good.preflight.return_value = self._result("ok", "222222222222")
            adapter_cls.for_account.side_effect = [bad, good]

        result, loop_cls, mock_build = self._run(monkeypatch, "multi", setup, accounts)

        assert result["statusCode"] == 200
        assert loop_cls.return_value.run.call_count == 1
        errors = mock_build.call_args.kwargs["scan_errors"]
        assert [e["account_id"] for e in errors] == ["111111111111"]
        assert errors[0]["kind"] == "preflight"
        assert len(mock_build.call_args.kwargs["preflight"]["accounts"]) == 2

    def test_multi_account_all_preflight_failures_raise(self, monkeypatch):
        from core.errors import PreflightFailedError

        accounts = [
            {
                "id": "111111111111",
                "name": "a",
                "role_arn": "arn:aws:iam::111111111111:role/r",
            },
            {
                "id": "222222222222",
                "name": "b",
                "role_arn": "arn:aws:iam::222222222222:role/r",
            },
        ]

        def setup(adapter_cls):
            adapter = MagicMock()
            adapter.preflight.return_value = self._result()
            adapter_cls.for_account.return_value = adapter

        exc, loop_cls, _ = self._run(monkeypatch, "multi", setup, accounts)

        assert isinstance(exc, PreflightFailedError)
        loop_cls.return_value.run.assert_not_called()


class TestHandlerAgentFailureMultiAccount:
    ACCOUNTS = [
        {
            "id": "111111111111",
            "name": "a",
            "role_arn": "arn:aws:iam::111111111111:role/r",
        },
        {
            "id": "222222222222",
            "name": "b",
            "role_arn": "arn:aws:iam::222222222222:role/r",
        },
    ]

    def _run(self, monkeypatch, run_side_effect):
        from contextlib import ExitStack
        from unittest.mock import patch

        monkeypatch.setenv("ACCOUNTS_MODE", "multi")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        monkeypatch.setenv("ACCOUNTS_CONFIG", json.dumps(self.ACCOUNTS))
        with ExitStack() as stack:
            stack.enter_context(patch("entrypoints.aws_lambda.notify_all"))
            stack.enter_context(
                patch("entrypoints.aws_lambda.build_slack_payload", return_value={})
            )
            mock_build = stack.enter_context(
                patch(
                    "entrypoints.aws_lambda.build_report", return_value=_fake_report()
                )
            )
            loop_cls = stack.enter_context(patch("entrypoints.aws_lambda.AgentLoop"))
            stack.enter_context(patch("entrypoints.aws_lambda.AWSAdapter"))
            stack.enter_context(patch("entrypoints.aws_lambda._build_ai_provider"))
            loop_cls.return_value.run.side_effect = run_side_effect
            from entrypoints.aws_lambda import handler

            try:
                return handler({}, None), mock_build
            except Exception as exc:  # noqa: BLE001
                return exc, mock_build

    def test_one_agent_failure_does_not_abort_other_accounts(self, monkeypatch):
        from core.errors import AgentDidNotSubmitError

        result, mock_build = self._run(
            monkeypatch, [AgentDidNotSubmitError("model said X"), ([], "fine")]
        )

        assert result["statusCode"] == 200
        errors = mock_build.call_args.kwargs["scan_errors"]
        assert [(e["account_id"], e["kind"]) for e in errors] == [
            ("111111111111", "agent")
        ]

    def test_every_agent_failure_raises(self, monkeypatch):
        from core.errors import AgentDidNotSubmitError

        exc, _ = self._run(
            monkeypatch,
            [AgentDidNotSubmitError("one"), AgentDidNotSubmitError("two")],
        )

        assert isinstance(exc, AgentDidNotSubmitError)


class TestDryRunLogging:
    def test_dry_run_does_not_claim_slack_was_delivered(self, monkeypatch):
        from contextlib import ExitStack
        from unittest.mock import patch

        from structlog.testing import capture_logs

        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("ACCOUNTS_MODE", "single")
        with ExitStack() as stack:
            stack.enter_context(
                patch("entrypoints.aws_lambda.notify_all", return_value=True)
            )
            stack.enter_context(
                patch("entrypoints.aws_lambda.build_slack_payload", return_value={})
            )
            stack.enter_context(
                patch(
                    "entrypoints.aws_lambda.build_report", return_value=_fake_report()
                )
            )
            loop_cls = stack.enter_context(patch("entrypoints.aws_lambda.AgentLoop"))
            stack.enter_context(patch("entrypoints.aws_lambda.AWSAdapter"))
            stack.enter_context(
                patch(
                    "entrypoints.aws_lambda._get_current_account_id", return_value="1"
                )
            )
            stack.enter_context(patch("entrypoints.aws_lambda._build_ai_provider"))
            loop_cls.return_value.run.return_value = ([], "ok")
            from entrypoints.aws_lambda import handler

            with capture_logs() as logs:
                handler({}, None)

        done = next(e for e in logs if e["event"] == "scan_complete")
        assert done["slack_delivered"] is False


class TestExpectAccount:
    def _run(self, monkeypatch, expect, actual="123456789012"):
        from contextlib import ExitStack
        from unittest.mock import patch

        monkeypatch.setenv("ACCOUNTS_MODE", "single")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        if expect:
            monkeypatch.setenv("ARGUS_EXPECT_ACCOUNT", expect)
        with ExitStack() as stack:
            stack.enter_context(patch("entrypoints.aws_lambda.notify_all"))
            stack.enter_context(
                patch("entrypoints.aws_lambda.build_slack_payload", return_value={})
            )
            stack.enter_context(
                patch(
                    "entrypoints.aws_lambda.build_report", return_value=_fake_report()
                )
            )
            loop_cls = stack.enter_context(patch("entrypoints.aws_lambda.AgentLoop"))
            adapter_cls = stack.enter_context(
                patch("entrypoints.aws_lambda.AWSAdapter")
            )
            stack.enter_context(
                patch(
                    "entrypoints.aws_lambda._get_current_account_id",
                    return_value=actual,
                )
            )
            stack.enter_context(patch("entrypoints.aws_lambda._build_ai_provider"))
            loop_cls.return_value.run.return_value = ([], "ok")
            from entrypoints.aws_lambda import handler

            try:
                return handler({}, None), loop_cls, adapter_cls
            except Exception as exc:  # noqa: BLE001
                return exc, loop_cls, adapter_cls

    def test_mismatch_fails_before_any_cloud_or_llm_call(self, monkeypatch):
        from core.errors import PreflightFailedError

        exc, loop_cls, adapter_cls = self._run(monkeypatch, "999999999999")

        assert isinstance(exc, PreflightFailedError)
        assert "999999999999" in str(exc) and "123456789012" in str(exc)
        loop_cls.return_value.run.assert_not_called()
        adapter_cls.for_account.assert_not_called()

    def test_match_runs_normally(self, monkeypatch):
        result, _, _ = self._run(monkeypatch, "123456789012")
        assert result["statusCode"] == 200

    def test_unset_means_no_guard(self, monkeypatch):
        result, _, _ = self._run(monkeypatch, None)
        assert result["statusCode"] == 200

    def test_unknown_identity_with_a_guard_fails_closed(self, monkeypatch):
        from core.errors import PreflightFailedError

        exc, _, _ = self._run(monkeypatch, "123456789012", actual="unknown")
        assert isinstance(exc, PreflightFailedError)

    def test_guard_still_applies_when_preflight_is_skipped(self, monkeypatch):
        from core.errors import PreflightFailedError

        monkeypatch.setenv("ARGUS_SKIP_PREFLIGHT", "true")
        exc, _, _ = self._run(monkeypatch, "999999999999")
        assert isinstance(exc, PreflightFailedError)
