from unittest.mock import MagicMock

import pytest

from core.errors import StrictCoverageError
from core.models.coverage import Coverage, TypeCoverage
from entrypoints._meta import ScanMeta


def _loop(discovered: int, analysed: int, window=None):
    loop = MagicMock()
    loop.coverage = Coverage(
        discovered,
        analysed,
        "cost_desc",
        True,
        ["us-east-1"],
        {"T": TypeCoverage(discovered, analysed)},
    )
    loop.scan_window = window
    return loop


def test_empty_meta_has_no_coverage():
    meta = ScanMeta()
    assert meta.coverage_dict() is None
    assert meta.summary() is None


def test_meta_merges_loops_across_accounts():
    meta = ScanMeta()
    meta.add_loop(_loop(10, 4, {"metrics_lookback_days": 14}))
    meta.add_loop(_loop(5, 5, {"metrics_lookback_days": 14}))

    assert meta.coverage_dict()["discovered"] == 15
    assert meta.summary() == {
        "discovered": 15,
        "analysed": 9,
        "dropped": 6,
        "truncated": True,
        "selection": "cost_desc",
        "discovery_complete": None,
        "free_config_skipped": 0,
        "metrics_lost_to_throttling": 0,
    }
    assert meta.scan_window == {"metrics_lookback_days": 14}


def test_meta_ignores_loops_without_real_coverage():
    loop = MagicMock()  # coverage is a MagicMock, not a Coverage
    meta = ScanMeta()
    meta.add_loop(loop)
    assert meta.coverage is None


def test_strict_raises_when_truncated():
    meta = ScanMeta()
    meta.add_loop(_loop(880, 200))
    with pytest.raises(StrictCoverageError, match="analysed 200 of 880"):
        meta.enforce_strict(True)


def test_strict_off_or_full_coverage_does_not_raise():
    meta = ScanMeta()
    meta.add_loop(_loop(880, 200))
    meta.enforce_strict(False)

    full = ScanMeta()
    full.add_loop(_loop(5, 5))
    full.enforce_strict(True)


def test_strict_also_fails_when_discovery_was_incomplete():
    loop = _loop(5, 5)
    loop.coverage.discovery_complete = False
    meta = ScanMeta()
    meta.add_loop(loop)

    with pytest.raises(StrictCoverageError, match="discovery"):
        meta.enforce_strict(True)
    meta.enforce_strict(False)


def test_llm_spend_is_summed_across_accounts():
    first = _loop(
        10, 4, {"llm_budget_usd": 2.0, "llm_estimate_usd": 0.3, "llm_spent_usd": 0.2}
    )
    second = _loop(
        5, 5, {"llm_budget_usd": 2.0, "llm_estimate_usd": 0.1, "llm_spent_usd": 0.05}
    )
    meta = ScanMeta()
    meta.add_loop(first)
    meta.add_loop(second)

    assert meta.scan_window["llm_spent_usd"] == 0.25
    assert meta.scan_window["llm_estimate_usd"] == 0.4
    assert meta.llm_summary() == {
        "spent_usd": 0.25,
        "estimate_usd": 0.4,
        "budget_usd": 4.0,
    }


def test_no_llm_numbers_means_no_summary():
    assert ScanMeta().llm_summary() is None


def test_plan_lines_are_listed_per_account_and_not_merged_into_one_plan():
    meta = ScanMeta()
    for line in ("plan A", "plan B"):
        meta.add_loop(
            _loop(
                10,
                4,
                {
                    "llm_budget_usd": 1.0,
                    "llm_estimate_usd": 0.3,
                    "llm_spent_usd": 0.2,
                    "llm_plan": {"line": line, "candidates": 3},
                    "llm_calibration": {"calls": 1},
                },
            )
        )

    assert meta.llm_summary()["plans"] == ["plan A", "plan B"]
    assert "llm_plan" not in meta.scan_window
    assert "llm_calibration" not in meta.scan_window


def test_a_single_account_keeps_its_plan_in_the_scan_window():
    meta = ScanMeta()
    meta.add_loop(
        _loop(
            10,
            4,
            {
                "llm_spent_usd": 0.2,
                "llm_plan": {"line": "plan A", "candidates": 3},
            },
        )
    )

    assert meta.scan_window["llm_plan"]["line"] == "plan A"
    assert meta.llm_summary()["plans"] == ["plan A"]
