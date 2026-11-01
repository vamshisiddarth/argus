"""
Cost basis hygiene: an estimate is never summed into a verified total unlabelled.
No cloud calls.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.models.finding import ResourceFinding
from core.reports.basis import (
    HEADLINE_VERIFIED_SHARE,
    basis_split_text,
    cost_summary,
    headline_noun,
    normalize_basis,
)
from core.reports.generator import (
    SCHEMA_VERSION,
    build_report,
    build_slack_payload,
    waste_caveat,
)
from core.reports.html import build_html_report
from core.reports.multi_cloud import merge_reports

SCAN_TIME = datetime(2026, 10, 30, 9, 0, 0, tzinfo=timezone.utc)


def _finding(rid: str, cost: float, basis: str | None, cloud: str = "aws"):
    return ResourceFinding(
        resource_id=rid,
        resource_type="AWS::EC2::Volume",
        cloud=cloud,  # type: ignore[arg-type]
        region="eu-west-1",
        estimated_monthly_cost=cost,
        waste_reason="Unattached.",
        recommendation="Delete after a snapshot.",
        priority="medium",
        metrics_summary={},
        tags={},
        scan_time=SCAN_TIME,
        name=rid,
        cost_basis=basis,
        confidence="medium",
    )


def _dicts(findings):
    return [f.to_dict() for f in findings]


MIXED = [
    _finding("vol-1", 100.0, "billed"),
    _finding("vol-2", 40.0, "list_price"),
    _finding("vol-3", 860.0, "model_estimate"),
    _finding("vol-4", 0.0, "unknown"),
    _finding("vol-5", 0.0, "unknown"),
]


class TestNormalizeBasis:
    @pytest.mark.parametrize(
        "basis,cost,expected",
        [
            ("billed", 10.0, "billed"),
            ("list_price", 10.0, "list_price"),
            ("model_estimate", 10.0, "model_estimate"),
            ("unknown", 0.0, "unknown"),
            ("estimated", 10.0, "model_estimate"),
            (None, 10.0, "model_estimate"),
            (None, 0.0, "unknown"),
            ("mixed", 5.0, "model_estimate"),
            ("unavailable", 0.0, "unknown"),
        ],
    )
    def test_maps_every_known_and_legacy_value(self, basis, cost, expected):
        assert normalize_basis(basis, cost) == expected

    def test_an_unpriced_finding_is_never_billed(self):
        assert normalize_basis("billed", 0.0) == "unknown"


class TestCostSummary:
    def test_splits_dollars_and_counts_by_basis(self):
        s = cost_summary(_dicts(MIXED))

        assert s["waste_by_basis"] == {
            "billed": 100.0,
            "list_price": 40.0,
            "model_estimate": 860.0,
            "unknown": 0.0,
        }
        assert s["findings_by_basis"] == {
            "billed": 1,
            "list_price": 1,
            "model_estimate": 1,
            "unknown": 2,
        }
        assert s["unpriced_findings"] == 2

    def test_verified_share_counts_only_billed_dollars(self):
        s = cost_summary(_dicts(MIXED))

        assert s["verified_waste_usd"] == 100.0
        assert s["verified_share"] == pytest.approx(0.1)
        assert s["headline_is_verified"] is False

    def test_a_mostly_billed_total_passes_the_headline_rule(self):
        findings = [
            _finding("a", 900.0, "billed"),
            _finding("b", 100.0, "model_estimate"),
        ]

        s = cost_summary(_dicts(findings))

        assert s["verified_share"] == pytest.approx(0.9)
        assert s["headline_is_verified"] is True
        assert HEADLINE_VERIFIED_SHARE <= 0.9

    def test_no_findings_has_no_share_and_nothing_to_warn_about(self):
        s = cost_summary([])

        assert s["verified_share"] is None
        assert s["headline_is_verified"] is True
        assert s["unpriced_findings"] == 0

    def test_bases_always_add_up_to_the_total(self):
        s = cost_summary(_dicts(MIXED))

        assert sum(s["waste_by_basis"].values()) == pytest.approx(1000.0)

    def test_old_reports_without_a_basis_count_as_unverified_estimates(self):
        legacy = [_finding("old", 50.0, None)]

        s = cost_summary(_dicts(legacy))

        assert s["waste_by_basis"]["model_estimate"] == 50.0
        assert s["verified_waste_usd"] == 0.0


class TestWording:
    def test_split_text_names_each_basis_and_the_unpriced_count(self):
        text = basis_split_text(cost_summary(_dicts(MIXED)))

        assert "$100.00 billed" in text
        assert "$40.00 list price" in text
        assert "$860.00 model estimate" in text
        assert "2 unpriced" in text

    def test_split_text_skips_empty_bases(self):
        text = basis_split_text(cost_summary(_dicts([_finding("a", 5.0, "billed")])))

        assert text == "$5.00 billed"

    def test_headline_noun_follows_how_much_is_billed(self):
        all_billed = {"findings": _dicts([_finding("a", 10.0, "billed")])}
        mostly = {
            "findings": _dicts(
                [_finding("a", 90.0, "billed"), _finding("b", 10.0, "model_estimate")]
            )
        }
        mostly_guess = {"findings": _dicts(MIXED)}

        assert headline_noun(all_billed) == "billed waste"
        assert headline_noun(mostly) == "estimated waste"
        assert headline_noun(mostly_guess) == "unverified waste estimate"

    def test_caveat_gives_the_basis_split_not_a_bare_total(self):
        report = build_report(MIXED, cloud="aws", executive_summary="x")

        caveat = waste_caveat(report)

        assert "estimate only, not billed, unverified" in caveat
        assert "$860.00 model estimate" in caveat
        assert "2 unpriced" in caveat

    def test_caveat_is_empty_when_everything_is_billed(self):
        report = build_report(
            [_finding("a", 10.0, "billed")], cloud="aws", executive_summary="x"
        )

        assert waste_caveat(report) == ""


class TestReportOutputs:
    def test_report_carries_the_summary_and_the_new_schema_version(self):
        report = build_report(MIXED, cloud="aws", executive_summary="x")

        assert SCHEMA_VERSION == "1.2.0"
        assert report["schema_version"] == "1.2.0"
        assert report["cost_summary"]["unpriced_findings"] == 2
        assert report["cost_summary"]["verified_waste_usd"] == 100.0
        assert sum(report["cost_summary"]["waste_by_basis"].values()) == pytest.approx(
            report["total_estimated_waste_usd"]
        )

    def test_slack_headline_is_labelled_unverified_when_mostly_guessed(self):
        report = build_report(MIXED, cloud="aws", executive_summary="x")

        payload = build_slack_payload(report)
        text = payload["blocks"][1]["fields"][0]["text"]

        assert "unverified waste estimate" in text
        assert "$860.00 model estimate" in text

    def test_slack_headline_stays_plain_when_billed(self):
        report = build_report(
            [_finding("a", 10.0, "billed")], cloud="aws", executive_summary="x"
        )

        payload = build_slack_payload(report)
        text = payload["blocks"][1]["fields"][0]["text"]

        assert "billed waste" in text
        assert "unverified" not in text

    def test_html_label_and_rows_tell_the_bases_apart(self):
        report = build_report(MIXED, cloud="aws", executive_summary="x")

        out = build_html_report(report)

        assert "unverified waste estimate / month" in out
        assert "$860.00 model estimate" in out
        assert ">unpriced<" in out
        assert "model est." in out
        assert ">list price<" in out

    def test_a_billed_row_has_no_basis_tag(self):
        report = build_report(
            [_finding("a", 10.0, "billed")], cloud="aws", executive_summary="x"
        )

        out = build_html_report(report)

        assert "model est." not in out and ">unpriced<" not in out

    def test_merged_reports_recompute_the_summary_from_all_findings(self):
        a = build_report(
            [_finding("a", 100.0, "billed")], cloud="aws", executive_summary="x"
        )
        b = build_report(
            [_finding("b", 300.0, "model_estimate", cloud="gcp")],
            cloud="gcp",
            executive_summary="y",
        )

        merged = merge_reports([a, b])

        assert merged["cost_summary"]["waste_by_basis"]["billed"] == 100.0
        assert merged["cost_summary"]["waste_by_basis"]["model_estimate"] == 300.0
        assert merged["cost_summary"]["verified_share"] == pytest.approx(0.25)
