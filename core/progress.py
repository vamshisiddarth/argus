"""
Scan progress for the command line.

The pipeline reports its stages to whatever reporter is installed; the default
does nothing, so Lambda, Cloud Run and Azure runs stay quiet. `argus scan` installs
StderrProgress: one live line in a terminal, plain throttled lines in a log.
"""

from __future__ import annotations

import contextlib
import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import IO

STAGES: tuple[tuple[str, str], ...] = (
    ("discover", "Discovering resources"),
    ("rules", "Applying rules"),
    ("evidence", "Collecting evidence"),
    ("model", "Reviewing with the model"),
    ("reports", "Building reports"),
)
_BAR_WIDTH = 20
_SPINNER = "|/-\\"
_CLEAR = "\r\x1b[K"


def _unit_for(count: int, unit: str) -> str:
    """'1 batch', '2 batches': plain English for the units the pipeline uses."""
    if count != 1:
        return unit
    if unit.endswith("ches"):
        return unit[:-2]
    return unit[:-1] if unit.endswith("s") else unit


def format_duration(seconds: float) -> str:
    whole = int(max(0, seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


class Progress:
    """The reporting interface. This base class ignores everything."""

    def stage(self, key: str, total: int | None = None, unit: str = "items") -> None:
        pass

    def advance(self, n: int = 1, detail: str = "") -> None:
        pass

    def extend(self, n: int, unit: str = "") -> None:
        pass

    def note(self, text: str) -> None:
        pass

    def tick(self) -> None:
        pass

    def finish(self, summary: str = "") -> None:
        pass

    def close(self, summary: str = "") -> None:
        pass


class NullProgress(Progress):
    pass


_current: Progress = NullProgress()


def get_progress() -> Progress:
    return _current


def set_progress(progress: Progress) -> Progress:
    """Install a reporter and return the one it replaced."""
    global _current
    previous, _current = _current, progress
    return previous


@contextlib.contextmanager
def use_progress(progress: Progress) -> Iterator[Progress]:
    previous = set_progress(progress)
    try:
        yield progress
    finally:
        set_progress(previous)


class StderrProgress(Progress):
    def __init__(
        self,
        stream: IO[str] | None = None,
        *,
        tty: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
        ticker: bool = True,
        width: int | None = None,
        min_line_interval: float = 10.0,
        heartbeat: float = 30.0,
        redraw_interval: float = 0.1,
    ) -> None:
        self._out = stream if stream is not None else sys.stderr
        self._tty = self._out.isatty() if tty is None else tty
        self._clock = clock
        self._width = width
        self._min_line = min_line_interval
        self._heartbeat = heartbeat
        self._redraw = redraw_interval
        self._lock = threading.RLock()
        self._key: str | None = None
        self._index = 0
        self._label = ""
        self._total: int | None = None
        self._unit = "items"
        self._done = 0
        self._detail = ""
        self._t0 = 0.0
        self._last_draw = float("-inf")
        self._last_line = 0.0
        self._next_pct = 10
        self._drawn = False
        self._spin = 0
        self._stop = threading.Event()
        self._closed = False
        self._thread: threading.Thread | None = None
        if ticker:
            self._thread = threading.Thread(target=self._run_ticker, daemon=True)
            self._thread.start()

    @property
    def done(self) -> int:
        return self._done

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def live(self) -> bool:
        """True while a terminal bar is drawn; other output should use note()."""
        return self._tty and not self._closed

    def stage(self, key: str, total: int | None = None, unit: str = "items") -> None:
        with self._lock:
            if self._key is not None:
                self.finish()
            self._key = key
            names = [k for k, _ in STAGES]
            labels = dict(STAGES)
            self._index = names.index(key) + 1 if key in names else 0
            self._label = labels.get(key, key)
            self._total = total
            self._unit = unit
            self._done = 0
            self._detail = ""
            self._t0 = self._clock()
            self._next_pct = 10
            if self._tty:
                self._draw(force=True)
            else:
                size = f": {total:,} {_unit_for(total, unit)}" if total else ""
                self._line(f"{self._prefix()}{size}")

    def advance(self, n: int = 1, detail: str = "") -> None:
        with self._lock:
            if self._key is None:
                return
            self._done += n
            if detail:
                self._detail = detail
            if self._tty:
                self._draw()
            else:
                self._milestone()

    def extend(self, n: int, unit: str = "") -> None:
        """Grow the total; for an unsized stage this is its first total."""
        with self._lock:
            if self._key is None:
                return
            if self._total is not None:
                self._total += n
                return
            self._total = n
            if unit:
                self._unit = unit
            if self._tty:
                self._draw(force=True)
            else:
                self._line(f"{self._prefix()}: {n:,} {_unit_for(n, self._unit)}")

    def note(self, text: str) -> None:
        with self._lock:
            if self._tty:
                self._clear()
                self._out.write(f"{_CLEAR}{text}\n")
                self._drawn = False
                if self._key is not None:
                    self._draw(force=True)
                self._out.flush()
            else:
                self._line(text, stamp=False)

    def tick(self) -> None:
        with self._lock:
            if self._key is None:
                return
            if self._tty:
                self._spin += 1
                self._draw(force=True)
            elif self._clock() - self._last_line >= self._heartbeat:
                count = (
                    f"{self._done:,}/{self._total:,} {self._unit}, "
                    if self._total
                    else ""
                )
                self._line(
                    f"{self._prefix()}: still working, {count}{self._elapsed()} elapsed"
                    f"{self._detail_suffix()}"
                )

    def finish(self, summary: str = "") -> None:
        with self._lock:
            if self._key is None:
                return
            text = f"{self._prefix()}: done"
            if self._total:
                text += f", {self._done:,} {_unit_for(self._done, self._unit)}"
            text += f" in {self._elapsed()}"
            if summary:
                text += f", {summary}"
            if self._tty:
                self._out.write(f"{_CLEAR}{text}\n")
                self._out.flush()
                self._drawn = False
            else:
                self._line(text)
            self._key = None

    def close(self, summary: str = "") -> None:
        with self._lock:
            if self._closed:
                return
            self.finish()
            if summary:
                self._line(summary, stamp=False)
            self._closed = True
        self._stop.set()

    def _run_ticker(self) -> None:
        while not self._stop.wait(0.5):
            self.tick()

    def _prefix(self) -> str:
        index = self._index or "?"
        return f"[{index}/{len(STAGES)}] {self._label}"

    def _detail_suffix(self) -> str:
        return f", {self._detail}" if self._detail else ""

    def _elapsed(self) -> str:
        return format_duration(self._clock() - self._t0)

    def _line(self, text: str, stamp: bool = True) -> None:
        self._out.write(text + "\n")
        self._out.flush()
        if stamp:
            self._last_line = self._clock()

    def _pct(self) -> int | None:
        if not self._total:
            return None
        return min(100, self._done * 100 // self._total)

    def _milestone(self) -> None:
        pct = self._pct()
        if pct is None or pct < self._next_pct:
            return
        if self._clock() - self._last_line < self._min_line:
            return
        self._next_pct = (pct // 10 + 1) * 10
        self._line(
            f"{self._prefix()}: {self._done:,}/{self._total:,} ({pct}%) "
            f"{self._elapsed()} elapsed{self._eta(prefix=', about ', suffix=' left')}"
            f"{self._detail_suffix()}"
        )

    def _eta(self, prefix: str = "", suffix: str = "") -> str:
        elapsed = self._clock() - self._t0
        if not self._total or self._done <= 0 or self._done >= self._total:
            return ""
        if elapsed < 3:
            return ""
        left = (self._total - self._done) / (self._done / elapsed)
        return f"{prefix}{format_duration(left)}{suffix}"

    def _columns(self) -> int:
        if self._width is not None:
            return self._width
        return shutil.get_terminal_size((100, 20)).columns

    def _draw(self, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._last_draw < self._redraw:
            return
        self._last_draw = now
        room = self._columns() - 1
        elapsed = self._elapsed()
        head = self._prefix()
        pct = self._pct()
        if pct is None:
            tail = f"{_SPINNER[self._spin % len(_SPINNER)]} {elapsed}"
            if self._detail:
                tail += f"  {self._detail}"
            line = f"{head}  {tail}"
        else:
            counts = f"{min(self._done, self._total or 0):,}/{self._total:,}"
            rest = f"{counts}  {pct}%  {elapsed}"
            eta = self._eta(prefix="about ", suffix=" left")
            if eta:
                rest += f"  {eta}"
            if self._detail:
                rest += f"  {self._detail}"
            available = room - len(head) - len(rest) - 6
            bar = ""
            if available >= 6:
                filled = _BAR_WIDTH * pct // 100
                width = min(_BAR_WIDTH, available)
                filled = min(width, width * pct // 100)
                bar = f"  [{'#' * filled}{'-' * (width - filled)}]"
            line = f"{head}{bar}  {rest}"
        self._out.write(_CLEAR + line[:room])
        self._out.flush()
        self._drawn = True

    def _clear(self) -> None:
        if self._drawn:
            self._out.write(_CLEAR)
            self._drawn = False
