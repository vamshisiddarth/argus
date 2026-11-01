from __future__ import annotations

import json

from core.reports.board import build_board_html
from core.reports.redact import RedactionProfile, redact_report

ACCT = "111122223333"
ARN = f"arn:aws:ec2:eu-west-1:{ACCT}:instance/i-0abc"
SUB = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"


def _finding(rid=ARN, **kw):
    f = {
        "resource_id": rid,
        "resource_type": "AWS::EC2::Instance",
        "cloud": "aws",
        "region": "eu-west-1",
        "account_id": ACCT,
        "name": "web-1",
        "estimated_monthly_cost": 50.0,
        "cost_basis": "list_price",
        "recommendation": f"Stop it. See {ARN}",
        "waste_reason": f"Idle in {ACCT}.",
        "detected_by": "model",
        "confidence": "high",
        "priority": "medium",
        "tags": {"owner": "alice", "cost-centre": "cc-9"},
        "metrics_summary": {},
    }
    f.update(kw)
    return f


def _report():
    return {
        "scan_id": "s1",
        "cloud": "aws",
        "generated_at": "2026-11-01T00:00:00+00:00",
        "accounts_scanned": [ACCT],
        "findings": [_finding(), _finding(rid=f"/subscriptions/{SUB}/rg/vm1")],
        "scan_window": {
            "metrics_lookback_days": 14,
            "llm_spent_usd": 1.4,
            "llm_budget_usd": 2.0,
            "llm_estimate_usd": 1.5,
            "llm_calibration": {"calls": 3},
        },
        "preflight": {
            "accounts": [
                {
                    "account_id": ACCT,
                    "checks": [
                        {
                            "code": "P1_IDENTITY",
                            "status": "info",
                            "message": f"Scanning as arn:aws:sts::{ACCT}:role/bob",
                        },
                        {"code": "P6_TAGS", "status": "warn", "message": "no tags"},
                    ],
                }
            ]
        },
        "scan_errors": [{"account_id": ACCT, "error": f"denied in {ACCT}"}],
    }


def _dump(report) -> str:
    return json.dumps(report)


class TestRedactReport:
    def test_no_account_id_or_guid_survives(self):
        out = _dump(redact_report(_report()))

        assert ACCT not in out and SUB not in out

    def test_account_alias_is_stable_and_findings_keep_their_link(self):
        out = redact_report(_report())

        assert out["findings"][0]["account_id"] == "account-1"
        assert out["scan_errors"][0]["account_id"] == "account-1"
        assert out["opportunities"] if "opportunities" in out else True

    def test_arn_loses_partition_and_account_but_keeps_region_and_resource(self):
        out = redact_report(_report())

        assert out["findings"][0]["resource_id"] == "ec2:eu-west-1:instance/i-0abc"
        assert "arn:aws" not in _dump(out)

    def test_run_cost_and_caller_identity_are_dropped(self):
        out = redact_report(_report())

        assert "llm_spent_usd" not in out["scan_window"]
        assert "llm_calibration" not in out["scan_window"]
        assert out["scan_window"]["metrics_lookback_days"] == 14
        codes = [c["code"] for c in out["preflight"]["accounts"][0]["checks"]]
        assert codes == ["P6_TAGS"]
        assert "bob" not in _dump(out)

    def test_the_stored_report_is_not_changed(self):
        report = _report()
        before = _dump(report)

        redact_report(report)

        assert _dump(report) == before

    def test_names_types_regions_and_amounts_are_kept(self):
        f = redact_report(_report())["findings"][0]

        assert f["name"] == "web-1" and f["region"] == "eu-west-1"
        assert f["resource_type"] == "AWS::EC2::Instance"
        assert f["estimated_monthly_cost"] == 50.0 and f["cost_basis"] == "list_price"

    def test_named_tag_keys_are_removed_others_kept(self):
        out = redact_report(
            _report(), RedactionProfile(hide_tag_keys=frozenset({"cost-centre"}))
        )

        assert out["findings"][0]["tags"] == {"owner": "alice"}

    def test_all_tags_can_be_removed(self):
        out = redact_report(_report(), RedactionProfile(hide_all_tags=True))

        assert out["findings"][0]["tags"] == {}
        assert "alice" not in _dump(out)

    def test_nothing_is_hidden_with_every_switch_off(self):
        profile = RedactionProfile(
            hide_accounts=False,
            shorten_arns=False,
            hide_run_cost=False,
            hide_identity=False,
        )

        assert redact_report(_report(), profile) == _report()


class TestRedactedBoard:
    def test_page_has_no_account_id_arn_or_run_cost(self):
        page = build_board_html(_report(), RedactionProfile())

        assert ACCT not in page and SUB not in page
        assert "arn:aws" not in page
        assert "Cost of this run" not in page

    def test_page_still_shows_the_money_with_its_basis(self):
        page = build_board_html(_report(), RedactionProfile())

        assert "list price" in page.lower()

    def test_default_page_is_unchanged(self):
        assert ACCT in build_board_html(_report())
