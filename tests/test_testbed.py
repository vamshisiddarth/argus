"""
The testbed's three artifacts must agree: the manifest, the Terraform that
creates the resources, and the offline fixture + baseline used by CI.
No cloud calls, no Terraform run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.calibration.manifest import load_manifest
from core.calibration.scoring import compare_to_baseline, score_report
from core.reports.generator import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent / "testbed"
MANIFEST = ROOT / "manifest.json"
TERRAFORM = ROOT / "terraform"
FIXTURE = ROOT / "fixtures" / "synthetic-scan.json"
BASELINE = ROOT / "baseline.json"


def _tf_text() -> str:
    return "\n".join(p.read_text() for p in sorted(TERRAFORM.glob("*.tf")))


def test_manifest_is_valid_and_has_the_planned_shape():
    m = load_manifest(MANIFEST)

    kinds = [r["kind"] for r in m["resources"]]
    assert len(m["classes"]) == 8
    assert kinds.count("waste") == 10
    assert kinds.count("decoy") == 3


def test_every_manifest_id_is_tagged_in_terraform_exactly_once():
    m = load_manifest(MANIFEST)
    tagged = re.findall(r'%s\s*=\s*"([^"]+)"' % re.escape(m["tag_key"]), _tf_text())

    assert sorted(tagged) == sorted(r["id"] for r in m["resources"])


def test_terraform_refuses_to_run_outside_the_sandbox_account():
    text = _tf_text()

    assert "allowed_account_ids = [var.sandbox_account_id]" in text
    assert not re.search(r"\b\d{12}\b", text), "no account id belongs in the code"


def test_costly_classes_are_off_by_default_and_match_the_manifest():
    m = load_manifest(MANIFEST)
    variables = (TERRAFORM / "variables.tf").read_text()
    costly = {k for k, v in m["classes"].items() if v["costly"]}

    assert re.search(
        r'variable "enable_costly_classes".*?default\s*=\s*false', variables, re.S
    )
    assert costly == {"idle_nat", "idle_lb", "idle_client_vpn"}


def test_provider_versions_are_pinned_with_digests():
    lock = (TERRAFORM / ".terraform.lock.hcl").read_text()

    assert 'provider "registry.terraform.io/hashicorp/aws"' in lock
    assert re.search(r'version\s*=\s*"\d+\.\d+\.\d+"', lock)
    assert "h1:" in lock and "zh:" in lock


def test_fixture_is_current_and_marked_synthetic():
    report = json.loads(FIXTURE.read_text())

    assert (
        report["schema_version"] == SCHEMA_VERSION
    ), "run python testbed/fixtures/make_synthetic_scan.py and refresh the baseline"
    assert "Not a recorded scan" in report["executive_summary"]


def test_fixture_scores_at_least_as_well_as_the_committed_baseline():
    m = load_manifest(MANIFEST)
    report = json.loads(FIXTURE.read_text())
    baseline = json.loads(BASELINE.read_text())

    card = score_report(report, m)

    assert compare_to_baseline(card, baseline) == []


def test_baseline_records_the_known_mistakes_in_the_fixture():
    baseline = json.loads(BASELINE.read_text())

    assert baseline["false_negatives"] == [
        "w-log-group-no-retention-1",
        "w-idle-client-vpn-1",
    ]
    assert baseline["false_positives"] == ["d-attached-vol-1"]
    assert baseline["cost"]["unpriced_true_positives"] == 1


@pytest.mark.parametrize("name", ["README.md", ".gitignore"])
def test_testbed_ships_its_docs_and_ignore_rules(name):
    assert (ROOT / name).exists()
