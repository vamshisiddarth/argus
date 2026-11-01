"""
Scan progress display. No threads started, no real time: a fake clock and an
in-memory stream.
"""

from __future__ import annotations

import io
import threading

import pytest

from core.progress import (
    NullProgress,
    StderrProgress,
    format_duration,
    get_progress,
    set_progress,
    use_progress,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make(tty: bool, **kw):
    out = io.StringIO()
    clock = Clock()
    p = StderrProgress(out, tty=tty, clock=clock, ticker=False, width=100, **kw)
    return p, out, clock


class TestDuration:
    @pytest.mark.parametrize(
        "seconds,text",
        [(0, "00:00"), (5, "00:05"), (125, "02:05"), (3725, "1:02:05"), (-3, "00:00")],
    )
    def test_formats(self, seconds, text):
        assert format_duration(seconds) == text


class TestNull:
    def test_every_call_is_a_harmless_no_op(self):
        p = NullProgress()

        p.stage("evidence", 10)
        p.advance(3, "x")
        p.extend(5)
        p.note("hello")
        p.finish("done")
        p.close()

    def test_the_default_reporter_is_the_null_one(self):
        assert isinstance(get_progress(), NullProgress)

    def test_use_progress_swaps_and_restores(self):
        before = get_progress()
        mine, _, _ = _make(tty=False)

        with use_progress(mine):
            assert get_progress() is mine

        assert get_progress() is before

    def test_set_progress_returns_the_previous_reporter(self):
        before = get_progress()
        mine, _, _ = _make(tty=False)

        previous = set_progress(mine)
        set_progress(previous)

        assert previous is before and get_progress() is before


class TestPlainMode:
    def test_stage_start_names_the_step_and_the_size(self):
        p, out, _ = _make(tty=False)

        p.stage("evidence", 1531, "resources")

        assert out.getvalue() == "[3/5] Collecting evidence: 1,531 resources\n"

    def test_lines_are_throttled_by_percent_and_by_time(self):
        p, out, clock = _make(tty=False, min_line_interval=10.0)
        p.stage("evidence", 100)
        out.truncate(0)
        out.seek(0)

        for _ in range(30):
            p.advance(1)
        assert out.getvalue() == ""
        clock.advance(11)
        p.advance(1)

        lines = out.getvalue().strip().splitlines()
        assert len(lines) == 1
        assert "31/100 (31%)" in lines[0]
        assert "elapsed" in lines[0]

    def test_a_milestone_is_not_repeated_until_the_next_step(self):
        p, out, clock = _make(tty=False, min_line_interval=0.0)
        p.stage("evidence", 100)
        out.truncate(0)
        out.seek(0)

        for _ in range(12):
            clock.advance(1)
            p.advance(1)

        assert len(out.getvalue().strip().splitlines()) == 1

    def test_finish_reports_the_count_and_the_time(self):
        p, out, clock = _make(tty=False)
        p.stage("evidence", 1531, "resources")
        clock.advance(252)
        p.advance(1531)

        p.finish()

        assert out.getvalue().splitlines()[-1] == (
            "[3/5] Collecting evidence: done, 1,531 resources in 04:12"
        )

    def test_finish_can_carry_a_summary(self):
        p, out, clock = _make(tty=False)
        p.stage("discover")
        clock.advance(41)

        p.finish("1,614 resources found")

        assert out.getvalue().splitlines()[-1] == (
            "[1/5] Discovering resources: done in 00:41, 1,614 resources found"
        )

    def test_a_silent_stage_gets_a_heartbeat(self):
        p, out, clock = _make(tty=False, heartbeat=30.0)
        p.stage("discover")
        out.truncate(0)
        out.seek(0)

        clock.advance(20)
        p.tick()
        assert out.getvalue() == ""
        clock.advance(15)
        p.tick()

        assert "still working" in out.getvalue()
        assert "00:35 elapsed" in out.getvalue()

    def test_notes_are_plain_lines(self):
        p, out, _ = _make(tty=False)

        p.note("LLM plan: 1531 candidates.")

        assert out.getvalue() == "LLM plan: 1531 candidates.\n"

    def test_starting_a_new_stage_closes_the_open_one(self):
        p, out, clock = _make(tty=False)
        p.stage("rules")
        clock.advance(3)

        p.stage("evidence", 10)

        text = out.getvalue()
        assert "[2/5] Applying rules: done in 00:03" in text
        assert text.rstrip().endswith("[3/5] Collecting evidence: 10 items")

    def test_extend_grows_the_total(self):
        p, out, clock = _make(tty=False, min_line_interval=0.0)
        p.stage("model", 4)
        p.extend(2)
        out.truncate(0)
        out.seek(0)
        clock.advance(5)

        p.advance(3)

        assert "3/6 (50%)" in out.getvalue()

    def test_no_control_characters_or_non_ascii_in_plain_output(self):
        p, out, clock = _make(tty=False, min_line_interval=0.0)
        p.stage("model", 10)
        for _ in range(10):
            clock.advance(2)
            p.advance(1, "$0.40 of $2.00")
        p.finish()

        text = out.getvalue()
        assert text.isascii()
        assert "\r" not in text and "\x1b" not in text


class TestSizingAStageLate:
    def test_extend_gives_an_unsized_stage_its_first_total(self):
        p, out, _ = _make(tty=False)
        p.stage("discover")
        out.truncate(0)
        out.seek(0)

        p.extend(18, "searches")

        assert out.getvalue() == "[1/5] Discovering resources: 18 searches\n"

    def test_later_growth_is_quiet_but_counted(self):
        p, out, clock = _make(tty=False, min_line_interval=0.0)
        p.stage("discover")
        p.extend(18, "searches")
        out.truncate(0)
        out.seek(0)

        p.extend(150)
        clock.advance(5)
        p.advance(17)

        assert out.getvalue().strip().splitlines() == [
            "[1/5] Discovering resources: 17/168 (10%) 00:05 elapsed, about 00:44 left"
        ]

    def test_a_late_total_turns_the_live_line_into_a_bar(self):
        p, out, clock = _make(tty=True)
        p.stage("discover")
        clock.advance(10)
        p.tick()
        assert "#" not in out.getvalue().split("\r")[-1]

        p.extend(10, "searches")
        assert "0/10" in out.getvalue().split("\r")[-1]
        clock.advance(1)
        p.advance(5)

        last = out.getvalue().split("\r")[-1]
        assert "[----" not in last and "#####" in last and "5/10" in last

    def test_extend_without_a_stage_does_nothing(self):
        p, out, _ = _make(tty=False)

        p.extend(5, "searches")

        assert out.getvalue() == ""


class TestDetailInPlainLines:
    def test_milestones_show_what_is_being_worked_on(self):
        p, out, clock = _make(tty=False, min_line_interval=0.0)
        p.stage("discover")
        p.extend(10, "searches")
        out.truncate(0)
        out.seek(0)
        clock.advance(4)

        p.advance(3, "eu-west-2 / ec2")

        assert (
            out.getvalue()
            .strip()
            .endswith("elapsed, about 00:09 left, eu-west-2 / ec2")
        )

    def test_heartbeats_show_it_too(self):
        p, out, clock = _make(tty=False, heartbeat=30.0, min_line_interval=1e9)
        p.stage("discover")
        p.extend(10, "searches")
        p.advance(2, "eu-west-2 / logs")
        out.truncate(0)
        out.seek(0)
        clock.advance(40)

        p.tick()

        assert "2/10 searches" in out.getvalue()
        assert out.getvalue().strip().endswith("eu-west-2 / logs")


class TestSingularUnits:
    @pytest.mark.parametrize(
        "unit,one",
        [("batches", "batch"), ("resources", "resource"), ("items", "item")],
    )
    def test_one_of_something_is_not_plural(self, unit, one):
        p, out, _ = _make(tty=False)

        p.stage("model", 1, unit)

        assert out.getvalue() == f"[4/5] Reviewing with the model: 1 {one}\n"

    def test_the_finish_line_is_singular_too(self):
        p, out, clock = _make(tty=False)
        p.stage("model", 1, "batches")
        clock.advance(12)
        p.advance(1)

        p.finish()

        assert out.getvalue().splitlines()[-1] == (
            "[4/5] Reviewing with the model: done, 1 batch in 00:12"
        )

    def test_more_than_one_stays_plural(self):
        p, out, _ = _make(tty=False)

        p.stage("model", 2, "batches")

        assert out.getvalue().endswith("2 batches\n")

    def test_a_stage_that_grew_from_one_is_plural_again(self):
        p, out, clock = _make(tty=False)
        p.stage("model", 1, "batches")
        p.extend(1)
        p.advance(2)
        clock.advance(3)

        p.finish()

        assert "done, 2 batches in" in out.getvalue()


class TestTtyMode:
    def test_draws_a_bar_a_percentage_and_the_elapsed_time(self):
        p, out, clock = _make(tty=True)
        p.stage("evidence", 100, "resources")
        clock.advance(65)

        p.advance(25)

        last = out.getvalue().split("\r")[-1]
        assert "[3/5] Collecting evidence" in last
        assert "[#####---------------]" in last
        assert "25/100" in last and "25%" in last
        assert "01:05" in last

    def test_shows_a_time_left_estimate_once_there_is_a_rate(self):
        p, out, clock = _make(tty=True)
        p.stage("evidence", 100)
        clock.advance(60)

        p.advance(20)

        assert "about 04:00 left" in out.getvalue().split("\r")[-1]

    def test_no_estimate_in_the_first_seconds(self):
        p, out, clock = _make(tty=True)
        p.stage("evidence", 100)
        clock.advance(1)

        p.advance(10)

        assert "left" not in out.getvalue().split("\r")[-1]

    def test_redraws_are_throttled(self):
        p, out, clock = _make(tty=True, redraw_interval=0.5)
        p.stage("evidence", 1000)
        before = out.getvalue().count("\r")

        for _ in range(50):
            clock.advance(0.001)
            p.advance(1)

        assert out.getvalue().count("\r") - before <= 1

    def test_the_detail_text_follows_the_bar(self):
        p, out, clock = _make(tty=True)
        p.stage("model", 26)
        clock.advance(10)

        p.advance(1, "$0.41 of $2.00")

        assert out.getvalue().split("\r")[-1].rstrip().endswith("$0.41 of $2.00")

    def test_a_line_never_exceeds_the_terminal_width(self):
        out = io.StringIO()
        clock = Clock()
        p = StderrProgress(out, tty=True, clock=clock, ticker=False, width=60)
        p.stage("model", 26)
        clock.advance(30)

        p.advance(3, "x" * 200)

        for chunk in out.getvalue().split("\r"):
            assert len(chunk.replace("\x1b[K", "")) <= 59

    def test_finish_leaves_one_clean_summary_line_ended_by_a_newline(self):
        p, out, clock = _make(tty=True)
        p.stage("evidence", 10, "resources")
        clock.advance(8)
        p.advance(10)

        p.finish()

        assert out.getvalue().endswith(
            "[3/5] Collecting evidence: done, 10 resources in 00:08\n"
        )

    def test_notes_do_not_land_on_top_of_the_bar(self):
        p, out, clock = _make(tty=True)
        p.stage("evidence", 10)
        clock.advance(5)
        p.advance(2)

        p.note("Coverage: analysed 10 of 10 resources.")

        text = out.getvalue()
        assert "\r\x1b[KCoverage: analysed 10 of 10 resources.\n" in text
        assert text.rstrip().split("\r")[-1].removeprefix("\x1b[K").startswith("[3/5]")

    def test_an_unsized_stage_shows_elapsed_time_and_a_spinner(self):
        p, out, clock = _make(tty=True)
        p.stage("discover")
        clock.advance(12)

        p.tick()

        last = out.getvalue().split("\r")[-1]
        assert "[1/5] Discovering resources" in last and "00:12" in last

    def test_only_the_clear_line_control_sequence_is_used(self):
        p, out, clock = _make(tty=True)
        p.stage("evidence", 10)
        clock.advance(5)
        p.advance(5)
        p.finish()

        stripped = out.getvalue().replace("\r", "").replace("\x1b[K", "")
        assert "\x1b" not in stripped
        assert stripped.isascii()


class TestSafety:
    def test_advances_from_many_threads_are_all_counted(self):
        p, _, _ = _make(tty=False, min_line_interval=1e9)
        p.stage("evidence", 800)

        def work() -> None:
            for _ in range(100):
                p.advance(1)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert p.done == 800

    def test_calls_without_a_stage_do_nothing(self):
        p, out, _ = _make(tty=True)

        p.advance(3)
        p.finish()
        p.tick()

        assert out.getvalue() == ""

    def test_an_unknown_stage_key_is_shown_as_given(self):
        p, out, _ = _make(tty=False)

        p.stage("something-new", 4)

        assert out.getvalue().startswith("[?/5] something-new")

    def test_close_stops_the_ticker_and_prints_the_summary(self):
        out = io.StringIO()
        p = StderrProgress(out, tty=False, ticker=True)

        p.close("Total time 00:01")

        assert out.getvalue() == "Total time 00:01\n"
        assert p.closed is True
        p.close()
