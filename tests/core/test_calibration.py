"""
Scoring a scan report against a labelled testbed manifest. No cloud calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.calibration.manifest import ManifestError, filter_manifest, load_manifest
from core.calibration.scoring import compare_to_baseline, render_markdown, score_report

TAG = "argus-testbed-id"


def _manifest() -> dict[str, Any]:
    return {
        "version": 1,
        "tag_key": TAG,
        "classes": {
            "unattached_volume": {
                "resource_type": "AWS::EC2::Volume",
                "target_recall": 0.95,
            },
            "idle_nat": {"resource_type": "AWS::EC2::NatGateway", "target_recall": 0.9},
        },
        "resources": [
            {
                "id": "w-vol-1",
                "class": "unattached_volume",
                "kind": "waste",
                "expected_monthly_usd": 10.0,
            },
            {
                "id": "w-vol-2",
                "class": "unattached_volume",
                "kind": "waste",
                "expected_monthly_usd": 20.0,
            },
            {
                "id": "w-nat-1",
                "class": "idle_nat",
                "kind": "waste",
                "expected_monthly_usd": 33.0,
            },
            {"id": "d-vol-1", "class": "unattached_volume", "kind": "decoy"},
        ],
    }


def _finding(
    tag: str | None,
    cost: float = 10.0,
    basis: str = "model_estimate",
    metrics: dict[str, Any] | None = None,
    detected_by: str = "model",
) -> dict[str, Any]:
    return {
        "resource_id": f"id-{tag}",
        "resource_type": "AWS::EC2::Volume",
        "estimated_monthly_cost": cost,
        "cost_basis": basis,
        "detected_by": detected_by,
        "metrics_summary": {"metrics": metrics if metrics is not None else {"x": 1}},
        "tags": {TAG: tag} if tag else {},
    }


def _report(findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "1.2.0",
        "findings": findings,
        "estimated_agent_cost_usd": 1.5,
        **extra,
    }


PERFECT = [
    _finding("w-vol-1", 10.0),
    _finding("w-vol-2", 20.0),
    _finding("w-nat-1", 33.0),
]


class TestManifest:
    def test_loads_a_valid_manifest(self, tmp_path):
        p = tmp_path / "m.json"
        p.write_text(json.dumps(_manifest()))

        m = load_manifest(p)

        assert m["tag_key"] == TAG
        assert len(m["resources"]) == 4

    @pytest.mark.parametrize(
        "mutate,fragment",
        [
            (lambda m: m["resources"].append(dict(m["resources"][0])), "duplicate"),
            (lambda m: m["resources"][0].update(**{"class": "nope"}), "unknown class"),
            (lambda m: m["resources"][0].update(kind="maybe"), "kind"),
            (lambda m: m.pop("tag_key"), "tag_key"),
            (lambda m: m["resources"][0].update(expected_monthly_usd=-1), "negative"),
            (
                lambda m: m["classes"]["idle_nat"].update(target_recall=1.5),
                "target_recall",
            ),
        ],
    )
    def test_rejects_a_bad_manifest(self, mutate, fragment):
        m = _manifest()
        mutate(m)

        with pytest.raises(ManifestError, match=fragment):
            load_manifest(m)


class TestScoring:
    def test_a_perfect_report_scores_one(self):
        s = score_report(_report(PERFECT), _manifest())

        assert s["recall"] == 1.0
        assert s["precision"] == 1.0
        assert s["false_negatives"] == []
        assert s["false_positives"] == []

    def test_missed_waste_lowers_recall_and_is_named(self):
        s = score_report(_report(PERFECT[:2]), _manifest())

        assert s["recall"] == pytest.approx(2 / 3)
        assert s["false_negatives"] == ["w-nat-1"]
        assert s["by_class"]["idle_nat"]["recall"] == 0.0
        assert s["by_class"]["idle_nat"]["target_met"] is False

    def test_a_flagged_decoy_lowers_precision_and_is_named(self):
        findings = PERFECT + [_finding("d-vol-1", 5.0)]

        s = score_report(_report(findings), _manifest())

        assert s["precision"] == pytest.approx(3 / 4)
        assert s["false_positives"] == ["d-vol-1"]
        assert s["recall"] == 1.0

    def test_findings_outside_the_testbed_are_counted_not_penalised(self):
        findings = PERFECT + [_finding(None), _finding("not-in-manifest")]

        s = score_report(_report(findings), _manifest())

        assert s["precision"] == 1.0
        assert s["unlabelled_findings"] == 2

    def test_class_targets_are_checked_per_class(self):
        s = score_report(_report(PERFECT[:1]), _manifest())

        assert s["by_class"]["unattached_volume"]["recall"] == 0.5
        assert s["by_class"]["unattached_volume"]["target_met"] is False
        assert s["by_class"]["unattached_volume"]["target"] == 0.95

    def test_cost_error_is_relative_to_the_expected_amount(self):
        findings = [
            _finding("w-vol-1", 20.0),
            _finding("w-vol-2", 20.0),
            _finding("w-nat-1", 33.0),
        ]

        s = score_report(_report(findings), _manifest())

        assert s["cost"]["errors"]["w-vol-1"] == pytest.approx(1.0)
        assert s["cost"]["errors"]["w-vol-2"] == 0.0
        assert s["cost"]["median_error"] == 0.0
        assert s["cost"]["max_error"] == pytest.approx(1.0)

    def test_an_unpriced_true_positive_is_counted_not_scored_as_zero_error(self):
        findings = [_finding("w-vol-1", 0.0, "unknown"), _finding("w-vol-2", 20.0)]

        s = score_report(_report(findings), _manifest())

        assert s["cost"]["unpriced_true_positives"] == 1
        assert "w-vol-1" not in s["cost"]["errors"]

    def test_verified_share_covers_the_true_positives(self):
        findings = [
            _finding("w-vol-1", 10.0, "billed"),
            _finding("w-vol-2", 30.0, "model_estimate"),
        ]

        s = score_report(_report(findings), _manifest())

        assert s["cost"]["verified_share"] == pytest.approx(0.25)

    def test_evidence_is_complete_with_metrics_or_a_rule(self):
        findings = [
            _finding("w-vol-1", metrics={"cpu": 1.0}),
            _finding("w-vol-2", metrics={}, detected_by="rule:ebs-volume-unattached"),
            _finding("w-nat-1", metrics={}),
        ]

        s = score_report(_report(findings), _manifest())

        assert s["evidence_complete_share"] == pytest.approx(2 / 3)

    def test_run_economics_are_copied_from_the_report(self):
        s = score_report(
            _report(PERFECT, scan_window={"llm_spent_usd": 1.25}), _manifest()
        )

        assert s["llm_cost_usd"] == 1.25
        assert s["findings_total"] == 3

    def test_no_findings_scores_zero_recall_and_no_precision(self):
        s = score_report(_report([]), _manifest())

        assert s["recall"] == 0.0
        assert s["precision"] is None


class TestBaseline:
    def _baseline(self):
        return score_report(_report(PERFECT), _manifest())

    def test_equal_or_better_is_not_a_regression(self):
        assert compare_to_baseline(self._baseline(), self._baseline()) == []

    def test_lower_recall_is_a_regression(self):
        worse = score_report(_report(PERFECT[:2]), _manifest())

        problems = compare_to_baseline(worse, self._baseline())

        assert any("recall" in p for p in problems)
        assert any("idle_nat" in p for p in problems)

    def test_lower_precision_is_a_regression(self):
        worse = score_report(_report(PERFECT + [_finding("d-vol-1")]), _manifest())

        assert any(
            "precision" in p for p in compare_to_baseline(worse, self._baseline())
        )

    def test_higher_cost_error_beyond_tolerance_is_a_regression(self):
        base = self._baseline()
        worse = score_report(
            _report([_finding("w-vol-1", 25.0), _finding("w-vol-2", 20.0), PERFECT[2]]),
            _manifest(),
        )

        assert any("cost error" in p for p in compare_to_baseline(worse, base))
        assert compare_to_baseline(worse, base, tolerance=2.0) == []

    def test_lower_verified_share_is_a_regression(self):
        base = score_report(_report([_finding("w-vol-1", 10.0, "billed")]), _manifest())
        worse = score_report(_report([_finding("w-vol-1", 10.0)]), _manifest())

        assert any("verified" in p for p in compare_to_baseline(worse, base))


class TestMarkdown:
    def test_lists_metrics_classes_and_misses(self):
        s = score_report(_report(PERFECT[:2] + [_finding("d-vol-1")]), _manifest())

        md = render_markdown(s)

        assert "Recall" in md and "Precision" in md
        assert "unattached_volume" in md and "idle_nat" in md
        assert "w-nat-1" in md and "d-vol-1" in md


class TestCli:
    def _write(self, tmp_path: Path, findings) -> tuple[Path, Path]:
        r = tmp_path / "report.json"
        m = tmp_path / "manifest.json"
        r.write_text(json.dumps(_report(findings)))
        m.write_text(json.dumps(_manifest()))
        return r, m

    def test_writes_json_and_markdown_and_exits_zero(self, tmp_path):
        from core.calibration.__main__ import main

        r, m = self._write(tmp_path, PERFECT)
        out_json, out_md = tmp_path / "s.json", tmp_path / "s.md"

        code = main(
            ["score", "--report", str(r), "--manifest", str(m)]
            + ["--json", str(out_json), "--md", str(out_md)]
        )

        assert code == 0
        assert json.loads(out_json.read_text())["recall"] == 1.0
        assert "Recall" in out_md.read_text()

    def test_exits_one_when_the_baseline_regresses(self, tmp_path):
        from core.calibration.__main__ import main

        r, m = self._write(tmp_path, PERFECT[:2])
        base = tmp_path / "base.json"
        base.write_text(json.dumps(score_report(_report(PERFECT), _manifest())))

        code = main(
            ["score", "--report", str(r), "--manifest", str(m), "--baseline", str(base)]
        )

        assert code == 1


class TestExcludeClasses:
    def test_removes_the_classes_and_their_resources(self):
        m = filter_manifest(_manifest(), {"idle_nat"})

        assert "idle_nat" not in m["classes"]
        assert [r["id"] for r in m["resources"]] == ["w-vol-1", "w-vol-2", "d-vol-1"]

    def test_scoring_a_partial_deployment_does_not_count_the_rest_as_misses(self):
        m = filter_manifest(_manifest(), {"idle_nat"})

        s = score_report(_report(PERFECT[:2]), m)

        assert s["recall"] == 1.0
        assert s["false_negatives"] == []

    def test_an_unknown_class_name_is_an_error(self):
        with pytest.raises(ManifestError, match="unknown class"):
            filter_manifest(_manifest(), {"nope"})

    def test_the_input_manifest_is_not_modified(self):
        original = _manifest()

        filter_manifest(original, {"idle_nat"})

        assert "idle_nat" in original["classes"]

    def test_cli_flag_applies_the_filter(self, tmp_path):
        from core.calibration.__main__ import main

        r = tmp_path / "report.json"
        m = tmp_path / "manifest.json"
        out = tmp_path / "s.json"
        r.write_text(json.dumps(_report(PERFECT[:2])))
        m.write_text(json.dumps(_manifest()))

        main(
            ["score", "--report", str(r), "--manifest", str(m)]
            + ["--exclude-class", "idle_nat", "--json", str(out)]
        )

        assert json.loads(out.read_text())["recall"] == 1.0
