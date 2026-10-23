"""Exit codes for `argus scan`: 2 budget, 3 agent did not submit, 4 preflight."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.errors import (
    EXIT_AGENT_NO_SUBMIT,
    EXIT_BUDGET_EXCEEDED,
    EXIT_PREFLIGHT_FAILED,
    AgentDidNotSubmitError,
    PreflightFailedError,
)

_SCAN_ENV_VARS = (
    "ARGUS_EXPECT_ACCOUNT",
    "ARGUS_SKIP_PREFLIGHT",
    "STRICT_COVERAGE",
    "METRICS_LOOKBACK_DAYS",
    "MAX_RESOURCES_PER_SCAN",
)


@pytest.fixture(autouse=True)
def _restore_scan_env(monkeypatch):
    """main() writes these straight into os.environ; make teardown remove them."""
    for var in _SCAN_ENV_VARS:
        monkeypatch.setenv(var, "placeholder")
        monkeypatch.delenv(var)


def _scan(argv=None):
    from entrypoints.cli import main

    main(argv or ["--cloud", "aws", "--run-now"])


class TestScanExitCodes:
    def test_constants(self):
        assert (EXIT_BUDGET_EXCEEDED, EXIT_AGENT_NO_SUBMIT, EXIT_PREFLIGHT_FAILED) == (
            2,
            3,
            4,
        )

    @patch("entrypoints.aws_lambda.handler")
    def test_agent_did_not_submit_exits_3(self, mock_handler, capsys):
        mock_handler.side_effect = AgentDidNotSubmitError("model said: 9 idle groups")

        with pytest.raises(SystemExit) as exc:
            _scan()

        assert exc.value.code == 3
        assert "9 idle groups" in capsys.readouterr().err

    @patch("entrypoints.aws_lambda.handler")
    def test_preflight_failure_exits_4(self, mock_handler, capsys):
        mock_handler.side_effect = PreflightFailedError("no aggregator index")

        with pytest.raises(SystemExit) as exc:
            _scan()

        assert exc.value.code == 4
        assert "no aggregator index" in capsys.readouterr().err

    @patch("entrypoints.aws_lambda.handler")
    def test_budget_exceeded_still_exits_2(self, mock_handler):
        mock_handler.return_value = {"statusCode": 200, "budget_exceeded": True}

        with pytest.raises(SystemExit) as exc:
            _scan()

        assert exc.value.code == 2


class TestCoverageCli:
    @patch("entrypoints.aws_lambda.handler")
    def test_prints_coverage_summary_line(self, mock_handler, capsys):
        mock_handler.return_value = {
            "statusCode": 200,
            "coverage": {
                "discovered": 880,
                "analysed": 200,
                "dropped": 680,
                "truncated": True,
                "selection": "stratified_by_type",
            },
        }

        _scan()

        err = capsys.readouterr().err
        assert "analysed 200 of 880" in err
        assert "680 not analysed" in err
        assert "stratified_by_type" in err

    @patch("entrypoints.aws_lambda.handler")
    def test_strict_coverage_flag_sets_env(self, mock_handler, monkeypatch):
        import os

        monkeypatch.delenv("STRICT_COVERAGE", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        _scan(["--cloud", "aws", "--run-now", "--strict-coverage"])

        assert os.environ["STRICT_COVERAGE"] == "true"
        monkeypatch.delenv("STRICT_COVERAGE", raising=False)

    @patch("entrypoints.aws_lambda.handler")
    def test_strict_coverage_failure_exits_1_with_message(self, mock_handler, capsys):
        from core.errors import StrictCoverageError

        mock_handler.side_effect = StrictCoverageError("analysed 1 of 9")

        with pytest.raises(SystemExit) as exc:
            _scan()

        assert exc.value.code == 1
        assert "analysed 1 of 9" in capsys.readouterr().err


class TestPreflightCli:
    @patch("entrypoints.aws_lambda.handler")
    def test_skip_preflight_flag_sets_env(self, mock_handler, monkeypatch):
        import os

        monkeypatch.delenv("ARGUS_SKIP_PREFLIGHT", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        _scan(["--cloud", "aws", "--run-now", "--skip-preflight"])

        assert os.environ["ARGUS_SKIP_PREFLIGHT"] == "true"
        monkeypatch.delenv("ARGUS_SKIP_PREFLIGHT", raising=False)

    @patch("entrypoints.aws_lambda.handler")
    def test_prints_preflight_warnings_and_skipped_state(self, mock_handler, capsys):
        mock_handler.return_value = {
            "statusCode": 200,
            "preflight": {
                "skipped": False,
                "warnings": ["P6_VIEW_TAGS: The default view does not include tags"],
            },
        }

        _scan()

        err = capsys.readouterr().err
        assert "Preflight warning: P6_VIEW_TAGS" in err

        mock_handler.return_value = {
            "statusCode": 200,
            "preflight": {"skipped": True, "warnings": []},
        }
        _scan()
        assert "Preflight was SKIPPED" in capsys.readouterr().err


class TestFlagsBeforeSubcommand:
    @patch("entrypoints.aws_lambda.handler")
    def test_top_level_flags_survive_the_scan_subcommand(
        self, mock_handler, monkeypatch
    ):
        import os

        for var in ("METRICS_LOOKBACK_DAYS", "STRICT_COVERAGE", "ARGUS_SKIP_PREFLIGHT"):
            monkeypatch.delenv(var, raising=False)
        mock_handler.return_value = {"statusCode": 200}

        _scan(
            [
                "--lookback-days",
                "14",
                "--strict-coverage",
                "--skip-preflight",
                "scan",
                "--cloud",
                "aws",
            ]
        )

        assert os.environ["METRICS_LOOKBACK_DAYS"] == "14"
        assert os.environ["STRICT_COVERAGE"] == "true"
        assert os.environ["ARGUS_SKIP_PREFLIGHT"] == "true"
        for var in ("METRICS_LOOKBACK_DAYS", "STRICT_COVERAGE", "ARGUS_SKIP_PREFLIGHT"):
            monkeypatch.delenv(var, raising=False)

    @patch("entrypoints.aws_lambda.handler")
    def test_scan_defaults_still_apply_without_flags(self, mock_handler, monkeypatch):
        import os

        monkeypatch.delenv("METRICS_LOOKBACK_DAYS", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        _scan(["scan", "--cloud", "aws"])

        assert os.environ["METRICS_LOOKBACK_DAYS"] == "90"
        monkeypatch.delenv("METRICS_LOOKBACK_DAYS", raising=False)


class TestExpectAccountCli:
    @patch("entrypoints.aws_lambda.handler")
    def test_expect_account_flag_sets_env(self, mock_handler, monkeypatch):
        import os

        monkeypatch.delenv("ARGUS_EXPECT_ACCOUNT", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        _scan(["--cloud", "aws", "--run-now", "--expect-account", "297805609304"])

        assert os.environ["ARGUS_EXPECT_ACCOUNT"] == "297805609304"
        monkeypatch.delenv("ARGUS_EXPECT_ACCOUNT", raising=False)

    @patch("entrypoints.aws_lambda.handler")
    def test_expect_account_before_subcommand_survives(self, mock_handler, monkeypatch):
        import os

        monkeypatch.delenv("ARGUS_EXPECT_ACCOUNT", raising=False)
        mock_handler.return_value = {"statusCode": 200}

        _scan(["--expect-account", "111111111111", "scan", "--cloud", "aws"])

        assert os.environ["ARGUS_EXPECT_ACCOUNT"] == "111111111111"
        monkeypatch.delenv("ARGUS_EXPECT_ACCOUNT", raising=False)


class TestDiscoveryCli:
    @patch("entrypoints.aws_lambda.handler")
    def test_summary_mentions_incomplete_discovery(self, mock_handler, capsys):
        mock_handler.return_value = {
            "statusCode": 200,
            "coverage": {
                "discovered": 1000,
                "analysed": 200,
                "dropped": 800,
                "truncated": True,
                "selection": "stratified_by_type",
                "discovery_complete": False,
            },
        }

        _scan()

        assert "discovery incomplete" in capsys.readouterr().err


class TestMaxResourcesCli:
    @patch("entrypoints.aws_lambda.handler")
    def test_flag_absent_leaves_the_budget_scaled_default_alone(self, mock_handler):
        import os

        mock_handler.return_value = {"statusCode": 200}

        _scan(["scan", "--cloud", "aws"])

        assert "MAX_RESOURCES_PER_SCAN" not in os.environ

    @patch("entrypoints.aws_lambda.handler")
    def test_flag_after_subcommand_is_applied(self, mock_handler):
        import os

        mock_handler.return_value = {"statusCode": 200}

        _scan(["scan", "--cloud", "aws", "--max-resources", "25"])

        assert os.environ["MAX_RESOURCES_PER_SCAN"] == "25"

    @patch("entrypoints.aws_lambda.handler")
    def test_flag_before_subcommand_survives(self, mock_handler):
        import os

        mock_handler.return_value = {"statusCode": 200}

        _scan(["--max-resources", "40", "scan", "--cloud", "aws"])

        assert os.environ["MAX_RESOURCES_PER_SCAN"] == "40"

    @patch("entrypoints.aws_lambda.handler")
    def test_legacy_run_now_without_flag_does_not_pin_200(self, mock_handler):
        import os

        mock_handler.return_value = {"statusCode": 200}

        _scan(["--cloud", "aws", "--run-now"])

        assert "MAX_RESOURCES_PER_SCAN" not in os.environ
