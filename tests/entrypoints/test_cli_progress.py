"""
`argus scan` shows progress on stderr and leaves stdout alone. No cloud calls.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.errors import AgentDidNotSubmitError
from core.progress import NullProgress, StderrProgress, get_progress


def _main(argv):
    from entrypoints.cli import main

    try:
        main(argv)
        return 0
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ARGUS_PROGRESS", raising=False)


def _spy(seen):
    def handler(event, context):
        seen.append(get_progress())
        return {"statusCode": 200, "findings_count": 0}

    return handler


class TestInstall:
    def test_a_scan_runs_with_a_progress_reporter(self):
        seen: list = []

        with patch("entrypoints.aws_lambda.handler", side_effect=_spy(seen)):
            code = _main(["scan", "--cloud", "aws"])

        assert code == 0
        assert isinstance(seen[0], StderrProgress)

    def test_the_reporter_is_removed_afterwards(self):
        with patch("entrypoints.aws_lambda.handler", side_effect=_spy([])):
            _main(["scan", "--cloud", "aws"])

        assert isinstance(get_progress(), NullProgress)

    def test_no_progress_flag_turns_it_off(self):
        seen: list = []

        with patch("entrypoints.aws_lambda.handler", side_effect=_spy(seen)):
            _main(["scan", "--cloud", "aws", "--no-progress"])

        assert isinstance(seen[0], NullProgress)

    @pytest.mark.parametrize("value", ["off", "0", "false", "no", "OFF"])
    def test_the_environment_variable_can_turn_it_off(self, monkeypatch, value):
        monkeypatch.setenv("ARGUS_PROGRESS", value)
        seen: list = []

        with patch("entrypoints.aws_lambda.handler", side_effect=_spy(seen)):
            _main(["scan", "--cloud", "aws"])

        assert isinstance(seen[0], NullProgress)

    def test_plain_forces_line_output_even_in_a_terminal(self, monkeypatch):
        monkeypatch.setenv("ARGUS_PROGRESS", "plain")
        seen: list = []

        with patch("entrypoints.aws_lambda.handler", side_effect=_spy(seen)):
            _main(["scan", "--cloud", "aws"])

        assert isinstance(seen[0], StderrProgress)
        assert seen[0]._tty is False

    def test_the_old_run_now_form_also_shows_progress(self):
        seen: list = []

        with patch("entrypoints.aws_lambda.handler", side_effect=_spy(seen)):
            _main(["--cloud", "aws", "--run-now"])

        assert isinstance(seen[0], StderrProgress)


class TestStreams:
    def test_stdout_stays_clean_json(self, capsys):
        with patch("entrypoints.aws_lambda.handler", side_effect=_spy([])):
            _main(["scan", "--cloud", "aws"])

        out = capsys.readouterr().out
        assert json.loads(out)["statusCode"] == 200

    def test_a_total_time_line_goes_to_stderr(self, capsys):
        with patch("entrypoints.aws_lambda.handler", side_effect=_spy([])):
            _main(["scan", "--cloud", "aws"])

        assert "Total time" in capsys.readouterr().err

    def test_nothing_is_added_to_stderr_when_off(self, capsys):
        with patch("entrypoints.aws_lambda.handler", side_effect=_spy([])):
            _main(["scan", "--cloud", "aws", "--no-progress"])

        assert "Total time" not in capsys.readouterr().err


class TestFailures:
    def test_the_reporter_is_removed_when_the_scan_fails(self):
        with patch(
            "entrypoints.aws_lambda.handler",
            side_effect=AgentDidNotSubmitError("no findings"),
        ):
            code = _main(["scan", "--cloud", "aws"])

        assert code == 3
        assert isinstance(get_progress(), NullProgress)

    def test_a_failed_scan_still_prints_its_error_after_a_clean_line(self, capsys):
        with patch(
            "entrypoints.aws_lambda.handler",
            side_effect=AgentDidNotSubmitError("no findings"),
        ):
            _main(["scan", "--cloud", "aws"])

        err = capsys.readouterr().err
        assert "Scan failed: no findings" in err
