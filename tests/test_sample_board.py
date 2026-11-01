"""The committed sample board must be what the generator produces today."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "examples" / "make_sample_board.py"
SAMPLE = ROOT / "examples" / "sample-board.html"


def _generator():
    spec = importlib.util.spec_from_file_location("make_sample_board", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_sample_is_current():
    assert (
        SAMPLE.read_text(encoding="ascii") == _generator().build()
    ), "run python examples/make_sample_board.py"


def test_the_generator_is_deterministic():
    gen = _generator()

    assert gen.build() == gen.build()


def test_the_sample_uses_only_the_placeholder_account_id():
    import re

    text = SAMPLE.read_text(encoding="ascii")

    assert set(re.findall(r"(?<![\w-])\d{12}(?![\w-])", text)) == {"123456789012"}


@pytest.mark.parametrize("needle", ["Argus", "Cost of this run", "Decide"])
def test_the_sample_shows_the_main_parts(needle):
    assert needle in SAMPLE.read_text(encoding="ascii")
