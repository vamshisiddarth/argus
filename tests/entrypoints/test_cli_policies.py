"""
Tests for `argus policies` subcommands added in Phase 2.
No real cloud calls, no Jira calls — pure unit tests.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> int:
    """Call cli.main() and return the process exit code (0 on success)."""
    from entrypoints.cli import main

    try:
        result = main(argv)
        return result if isinstance(result, int) else 0
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_policy(tmp_path: Path, filename: str = "rds.yaml") -> Path:
    content = textwrap.dedent("""\
        version: "1"
        policy_id: rds-resize
        name: Resize underutilized RDS
        resource_type: "AWS::RDS::DBInstance"
        action: resize
        weight: 10
        conditions:
          min_estimated_monthly_cost_usd: 50.0
          ai_priority: [high, medium]
    """)
    f = tmp_path / filename
    f.write_text(content)
    return f


def _write_report(tmp_path: Path) -> Path:
    report = {
        "scan_id": "test-scan",
        "cloud": "aws",
        "findings": [
            {
                "resource_id": "db-idle-01",
                "resource_type": "AWS::RDS::DBInstance",
                "cloud": "aws",
                "region": "us-east-1",
                "name": "idle-db",
                "estimated_monthly_cost": 120.0,
                "waste_reason": "Low CPU for 30 days",
                "recommendation": "Resize to db.t3.small",
                "priority": "high",
                "metrics_summary": {},
                "tags": {},
                "last_activity": None,
            }
        ],
    }
    f = tmp_path / "report.json"
    f.write_text(json.dumps(report))
    return f


# ---------------------------------------------------------------------------
# argus policies validate
# ---------------------------------------------------------------------------


class TestPoliciesValidate:
    def test_valid_policies_exits_zero(self, tmp_path, capsys):
        _write_policy(tmp_path)

        rc = _run(["policies", "validate", "--dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "policy loaded" in out or "policies loaded" in out

    def test_empty_dir_exits_zero_with_warning(self, tmp_path, capsys):

        rc = _run(["policies", "validate", "--dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No polic" in out or "0 policy" in out or "0 policies" in out

    def test_missing_dir_exits_zero_with_warning(self, tmp_path, capsys):

        rc = _run(["policies", "validate", "--dir", str(tmp_path / "nonexistent")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No polic" in out or "0 policy" in out or "0 policies" in out

    def test_invalid_policy_exits_nonzero(self, tmp_path, capsys):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not_a_policy: true\n")

        rc = _run(["policies", "validate", "--dir", str(tmp_path)])
        # load error → nonzero
        assert rc != 0

    def test_valid_policies_prints_count(self, tmp_path, capsys):
        _write_policy(tmp_path, "a.yaml")
        _write_policy(tmp_path, "b.yaml")
        # make second file have a different policy_id to avoid conflict
        (tmp_path / "b.yaml").write_text(textwrap.dedent("""\
            version: "1"
            policy_id: rds-delete
            name: Delete stopped RDS
            resource_type: "AWS::RDS::DBInstance"
            action: delete
            weight: 5
            conditions:
              min_estimated_monthly_cost_usd: 10.0
        """))

        rc = _run(["policies", "validate", "--dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2" in out


# ---------------------------------------------------------------------------
# argus policies plan
# ---------------------------------------------------------------------------


class TestPoliciesPlan:
    def test_plan_with_report_exits_zero(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        rc = _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        assert rc == 0

    def test_plan_shows_match(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        out = capsys.readouterr().out
        assert "MATCH" in out
        assert "rds-resize" in out

    def test_plan_shows_cost(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        out = capsys.readouterr().out
        assert "120.00" in out

    def test_plan_shows_action(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        out = capsys.readouterr().out
        assert "resize" in out

    def test_plan_no_match(self, tmp_path, capsys):
        _write_policy(tmp_path)
        # Report with finding that does NOT meet min cost (1.0 < 50.0)
        report_data = {
            "findings": [{
                "resource_id": "db-cheap",
                "resource_type": "AWS::RDS::DBInstance",
                "cloud": "aws",
                "region": "us-east-1",
                "name": None,
                "estimated_monthly_cost": 1.0,
                "waste_reason": "unused",
                "recommendation": "delete",
                "priority": "low",
                "metrics_summary": {},
                "tags": {},
                "last_activity": None,
            }],
        }
        report = tmp_path / "cheap.json"
        report.write_text(json.dumps(report_data))

        rc = _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No findings matched" in out

    def test_plan_no_source_exits_nonzero(self, tmp_path, capsys):
        _write_policy(tmp_path)

        rc = _run(["policies", "plan", "--dir", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "--report" in out or "Specify" in out

    def test_plan_live_without_cloud_exits_nonzero(self, tmp_path, capsys):
        _write_policy(tmp_path)

        rc = _run(["policies", "plan", "--dir", str(tmp_path), "--live"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "--cloud" in out

    def test_plan_missing_report_exits_nonzero(self, tmp_path, capsys):
        _write_policy(tmp_path)

        rc = _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(tmp_path / "nope.json"),
        ])
        assert rc == 1

    def test_plan_bad_policies_exits_nonzero(self, tmp_path, capsys):
        bad = tmp_path / "bad.yaml"
        bad.write_text("not_a_policy: true\n")
        report = _write_report(tmp_path)

        rc = _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        assert rc == 1

    def test_plan_output_has_header_box(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        out = capsys.readouterr().out
        assert "POLICY PLAN" in out
        assert "─" in out

    def test_plan_empty_dir_exits_zero(self, tmp_path, capsys):
        report = _write_report(tmp_path)

        rc = _run([
            "policies", "plan",
            "--dir", str(tmp_path / "empty"),
            "--report", str(report),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No policies" in out


# ---------------------------------------------------------------------------
# argus policies apply (dry-run)
# ---------------------------------------------------------------------------


class TestPoliciesApply:
    def test_apply_without_confirm_is_dryrun(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        rc = _run([
            "policies", "apply",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        # dry-run: "Would create" not "Creating"
        assert "Would create" in out

    def test_apply_with_confirm_notes_phase3(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        rc = _run([
            "policies", "apply",
            "--dir", str(tmp_path),
            "--report", str(report),
            "--confirm",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Phase 3" in out or "ticket creation" in out.lower()

    def test_apply_shows_apply_verb_in_header(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)

        _run([
            "policies", "apply",
            "--dir", str(tmp_path),
            "--report", str(report),
            "--confirm",
        ])
        out = capsys.readouterr().out
        assert "POLICY APPLY" in out


# ---------------------------------------------------------------------------
# argus policies docs
# ---------------------------------------------------------------------------


class TestPoliciesDocs:
    def test_docs_lists_all_types(self, capsys):

        rc = _run(["policies", "docs"])
        assert rc is None or rc == 0
        out = capsys.readouterr().out
        # should list at least one known resource type
        assert "AWS" in out or "GCP" in out or "AZURE" in out

    def test_docs_filter_by_cloud(self, capsys):

        _run(["policies", "docs", "--cloud", "aws"])
        out = capsys.readouterr().out
        assert "AWS" in out

    def test_docs_specific_type_known(self, capsys):

        _run(["policies", "docs", "AWS::RDS::DBInstance"])
        out = capsys.readouterr().out
        assert "AWS::RDS::DBInstance" in out
        assert "Tier 1" in out
        assert "Tier 2" in out or "none defined" in out.lower()

    def test_docs_specific_type_unknown(self, capsys):

        _run(["policies", "docs", "AWS::Fake::Resource"])
        out = capsys.readouterr().out
        assert "Unknown resource type" in out

    def test_docs_shows_actions(self, capsys):

        _run(["policies", "docs", "AWS::RDS::DBInstance"])
        out = capsys.readouterr().out
        # RDS should have at least one valid action listed
        assert "actions:" in out or "Valid actions:" in out

    def test_docs_shows_tier1_conditions(self, capsys):

        _run(["policies", "docs", "AWS::RDS::DBInstance"])
        out = capsys.readouterr().out
        assert "min_estimated_monthly_cost_usd" in out
        assert "ai_priority" in out
        assert "idle_days_min" in out

    def test_docs_shows_total_count(self, capsys):

        _run(["policies", "docs"])
        out = capsys.readouterr().out
        assert "resource types known" in out or "Total:" in out

    def test_docs_specific_type_shows_box(self, capsys):
        _run(["policies", "docs", "AWS::RDS::DBInstance"])
        out = capsys.readouterr().out
        assert "┌" in out and "└" in out

    def test_docs_specific_type_shows_tier_headers(self, capsys):
        _run(["policies", "docs", "AWS::RDS::DBInstance"])
        out = capsys.readouterr().out
        assert "▸ Tier 1" in out
        assert "▸ Tier 2" in out or "▸ Valid actions" in out

    def test_docs_list_shows_display_name_column(self, capsys):
        _run(["policies", "docs", "--cloud", "aws"])
        out = capsys.readouterr().out
        assert "Display Name" in out


class TestValidatePoliciesErrorFormatting:
    def test_load_error_shows_x_symbol(self, tmp_path, capsys):
        # A file that fails to load at all (bad YAML syntax) shows ✗
        bad = tmp_path / "bad.yaml"
        bad.write_text("not_a_policy: true\n")
        _run(["policies", "validate", "--dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert "✗" in out

    def test_validation_error_shows_tip(self, tmp_path, capsys):
        # Two policies with same policy_id + same weight → conflict error
        # This passes load but fails validate_policies
        (tmp_path / "a.yaml").write_text(textwrap.dedent("""\
            version: "1"
            policy_id: rds-resize
            name: Resize RDS A
            resource_type: "AWS::RDS::DBInstance"
            action: resize
            weight: 10
            conditions:
              min_estimated_monthly_cost_usd: 50.0
        """))
        (tmp_path / "b.yaml").write_text(textwrap.dedent("""\
            version: "1"
            policy_id: rds-resize
            name: Resize RDS B
            resource_type: "AWS::RDS::DBInstance"
            action: delete
            weight: 10
            conditions:
              min_estimated_monthly_cost_usd: 50.0
        """))
        rc = _run(["policies", "validate", "--dir", str(tmp_path)])
        out = capsys.readouterr().out
        # Either a conflict error was caught (nonzero) or a load dedup happened
        # Either way, something non-zero or the tip must appear
        assert rc != 0 or "Tip" in out or "✗" in out


class TestPlanNextStep:
    def test_plan_shows_next_step_hint(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)
        _run([
            "policies", "plan",
            "--dir", str(tmp_path),
            "--report", str(report),
        ])
        out = capsys.readouterr().out
        assert "Next step" in out or "--confirm" in out

    def test_apply_confirm_does_not_show_next_step(self, tmp_path, capsys):
        _write_policy(tmp_path)
        report = _write_report(tmp_path)
        _run([
            "policies", "apply",
            "--dir", str(tmp_path),
            "--report", str(report),
            "--confirm",
        ])
        out = capsys.readouterr().out
        assert "Next step" not in out


# ---------------------------------------------------------------------------
# _load_findings_from_report
# ---------------------------------------------------------------------------


class TestLoadFindingsFromReport:
    def test_loads_valid_report(self, tmp_path):
        report = _write_report(tmp_path)
        from entrypoints.cli import _load_findings_from_report

        findings = _load_findings_from_report(str(report))
        assert len(findings) == 1
        assert findings[0].resource_id == "db-idle-01"
        assert findings[0].estimated_monthly_cost == 120.0

    def test_missing_file_raises(self, tmp_path):
        from entrypoints.cli import _load_findings_from_report

        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            _load_findings_from_report(str(tmp_path / "ghost.json"))

    def test_empty_findings_list(self, tmp_path):
        report = tmp_path / "empty.json"
        report.write_text(json.dumps({"findings": []}))
        from entrypoints.cli import _load_findings_from_report

        findings = _load_findings_from_report(str(report))
        assert findings == []

    def test_finding_without_last_activity(self, tmp_path):
        report = tmp_path / "r.json"
        report.write_text(json.dumps({
            "findings": [{
                "resource_id": "ec2-x",
                "resource_type": "AWS::EC2::Instance",
                "cloud": "aws",
                "region": "us-west-2",
                "name": None,
                "estimated_monthly_cost": 50.0,
                "waste_reason": "idle",
                "recommendation": "terminate",
                "priority": "low",
                "metrics_summary": {},
                "tags": {},
                "last_activity": None,
            }]
        }))
        from entrypoints.cli import _load_findings_from_report

        findings = _load_findings_from_report(str(report))
        assert findings[0].last_activity is None

    def test_finding_with_last_activity(self, tmp_path):
        report = tmp_path / "r.json"
        report.write_text(json.dumps({
            "findings": [{
                "resource_id": "ec2-y",
                "resource_type": "AWS::EC2::Instance",
                "cloud": "aws",
                "region": "us-east-1",
                "name": "old-server",
                "estimated_monthly_cost": 80.0,
                "waste_reason": "idle",
                "recommendation": "terminate",
                "priority": "medium",
                "metrics_summary": {},
                "tags": {},
                "last_activity": "2026-01-01T00:00:00",
            }]
        }))
        from entrypoints.cli import _load_findings_from_report

        findings = _load_findings_from_report(str(report))
        assert findings[0].last_activity is not None
        assert findings[0].last_activity.year == 2026
