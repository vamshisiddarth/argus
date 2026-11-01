"""
Log lines and the live progress bar share a terminal. Logs must scroll above the
bar, never land on it. No cloud calls.
"""

from __future__ import annotations

import io
import logging

import pytest
import structlog

from core.log import configure_logging
from core.progress import NullProgress, StderrProgress, use_progress


@pytest.fixture(autouse=True)
def _restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _live():
    out = io.StringIO()
    clock = Clock()
    p = StderrProgress(out, tty=True, clock=clock, ticker=False, width=100)
    return p, out, clock


class TestLogsAboveTheBar:
    def test_a_log_line_clears_the_bar_prints_above_it_and_redraws(self):
        configure_logging()
        p, out, clock = _live()
        p.stage("evidence", 10, "resources")
        clock.now += 5
        p.advance(2)

        with use_progress(p):
            structlog.get_logger("t").info("something_happened", count=3)

        text = out.getvalue()
        assert "\r\x1b[K" in text
        line = [c for c in text.split("\r\x1b[K") if "something_happened" in c][0]
        assert line.endswith("\n")
        assert text.rstrip().split("\r")[-1].removeprefix("\x1b[K").startswith("[3/5]")

    def test_without_a_live_bar_logs_go_to_stderr_as_before(self, capsys):
        configure_logging()

        with use_progress(NullProgress()):
            structlog.get_logger("t").info("plain_event")

        assert "plain_event" in capsys.readouterr().err

    def test_in_plain_mode_logs_go_to_stderr_not_through_the_progress(self, capsys):
        configure_logging()
        out = io.StringIO()
        p = StderrProgress(out, tty=False, ticker=False)
        p.stage("evidence", 10)

        with use_progress(p):
            structlog.get_logger("t").info("plain_mode_event")

        assert "plain_mode_event" in capsys.readouterr().err
        assert "plain_mode_event" not in out.getvalue()

    def test_a_closed_bar_no_longer_captures_logs(self, capsys):
        configure_logging()
        p, out, _ = _live()
        p.stage("evidence", 10)
        p.close()

        with use_progress(p):
            structlog.get_logger("t").info("after_close")

        assert "after_close" in capsys.readouterr().err
        assert "after_close" not in out.getvalue()

    def test_levels_still_apply(self, capsys, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        configure_logging()
        p, out, _ = _live()
        p.stage("evidence", 10)

        with use_progress(p):
            structlog.get_logger("t").info("too_quiet")
            structlog.get_logger("t").warning("loud_enough")

        assert "too_quiet" not in out.getvalue()
        assert "loud_enough" in out.getvalue()


class TestHeartbeatShowsProgress:
    def test_a_sized_stage_heartbeat_includes_the_count(self):
        out = io.StringIO()
        clock = Clock()
        p = StderrProgress(
            out,
            tty=False,
            clock=clock,
            ticker=False,
            heartbeat=30.0,
            min_line_interval=1e9,
        )
        p.stage("model", 26, "batches")
        p.advance(7)
        out.truncate(0)
        out.seek(0)
        clock.now += 40

        p.tick()

        assert "7/26 batches" in out.getvalue()
        assert "still working" in out.getvalue()
