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
