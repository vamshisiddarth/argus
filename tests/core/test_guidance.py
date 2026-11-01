"""
Evidence, risk and check-first text for an opportunity. Deterministic templates;
no model, no cloud calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.opportunities.grouping import build_opportunities


def _f(
    rid: str,
    rtype: str = "AWS::EC2::Volume",
    rec: str = "Delete after a snapshot.",
    by: str = "model",
    conf: str = "high",
    cost: float = 10.0,
    basis: str = "list_price",
    metrics: dict[str, Any] | None = None,
    checked: bool = False,
    review: bool = False,
) -> dict[str, Any]:
    return {
        "resource_id": rid,
        "resource_type": rtype,
        "name": rid,
        "estimated_monthly_cost": cost,
        "cost_basis": basis,
        "recommendation": rec,
        "waste_reason": "Idle.",
        "detected_by": by,
        "confidence": conf,
        "priority": "medium",
        "tags": {},
        "review_required": review,
        "review_reasons": ["prod_like_name"] if review else [],
        "metrics_summary": {
            "metrics": metrics if metrics is not None else {"x": 1},
            "metrics_status": "ok",
            "last_activity_checked": checked,
        },
    }


def _one(findings):
    (opp,) = build_opportunities(findings)
    return opp


class TestShape:
    def test_every_opportunity_has_evidence_risk_and_steps(self):
        opp = _one([_f("a"), _f("b")])

        assert isinstance(opp["evidence"], list) and opp["evidence"]
        assert isinstance(opp["risk"], str) and opp["risk"]
        assert isinstance(opp["check_first"], list) and len(opp["check_first"]) >= 3
        assert all(
            isinstance(s, str) and s for s in opp["evidence"] + opp["check_first"]
        )

    def test_text_is_plain_ascii(self):
        for rec in (
            "Delete it.",
            "Right-size it.",
            "Stop it.",
            "Set retention.",
            "Review",
        ):
            opp = _one([_f("a", rec=rec), _f("b", rec=rec)])
            text = " ".join(opp["evidence"] + [opp["risk"]] + opp["check_first"])

            assert text.isascii(), rec

    def test_text_is_deterministic(self):
        one = _one([_f("a"), _f("b")])
        two = _one([_f("b"), _f("a")])

        assert (one["evidence"], one["risk"], one["check_first"]) == (
            two["evidence"],
            two["risk"],
            two["check_first"],
        )


class TestEvidence:
    def test_counts_rule_and_model_findings(self):
        opp = _one([_f("a", by="rule:x"), _f("b", by="rule:x"), _f("c")])

        assert any(
            "2 by deterministic rules, 1 by model review" in e for e in opp["evidence"]
        )

    def test_counts_members_with_metrics_and_activity_checks(self):
        findings = [
            _f("a", metrics={"cpu": 1}, checked=True),
            _f("b", metrics={}, checked=False),
        ]

        opp = _one(findings)

        text = " ".join(opp["evidence"])
        assert "Metrics available for 1 of 2" in text
        assert "Last activity checked for 1 of 2" in text

    def test_rule_findings_do_not_count_as_missing_metrics(self):
        findings = [_f("a", by="rule:x", metrics={}), _f("b", by="rule:x", metrics={})]

        opp = _one(findings)

        assert "Metrics available" not in " ".join(opp["evidence"])

    def test_names_the_cost_bases(self):
        opp = _one([_f("a", cost=5.0, basis="billed"), _f("b", cost=7.0)])

        assert any("billed" in e and "list price" in e for e in opp["evidence"])

    def test_states_the_lowest_confidence(self):
        opp = _one([_f("a", conf="high"), _f("b", conf="medium")])

        assert any("Lowest confidence: medium" in e for e in opp["evidence"])


class TestRisk:
    @pytest.mark.parametrize(
        "rec,fragment",
        [
            ("Delete it.", "cannot be undone"),
            ("Stop it.", "still bills"),
            ("Right-size it.", "memory"),
            ("Set a retention.", "permanently"),
            ("Review it.", "Do not act"),
        ],
    )
    def test_risk_follows_the_action(self, rec, fragment):
        opp = _one([_f("a", rec=rec), _f("b", rec=rec)])

        assert fragment in opp["risk"]

    def test_flagged_members_add_their_reasons(self):
        opp = _one([_f("a", review=True), _f("b", review=True)])

        assert "prod_like_name" in opp["risk"]

    def test_low_confidence_is_called_out(self):
        opp = _one([_f("a", conf="low"), _f("b", conf="low")])

        assert "low confidence" in opp["risk"].lower()

    def test_unpriced_members_are_called_out(self):
        opp = _one([_f("a", cost=0.0, basis="unknown"), _f("b", cost=4.0)])

        assert "1 member has no dollar figure" in opp["risk"]


class TestCheckFirst:
    def test_addresses_get_an_allowlist_step(self):
        opp = _one(
            [
                _f("a", "AWS::EC2::EIP", rec="Release it."),
                _f("b", "AWS::EC2::EIP", rec="Release it."),
            ]
        )

        assert any("allowlist" in s.lower() for s in opp["check_first"])

    def test_volumes_and_snapshots_get_a_backup_step(self):
        vol = _one([_f("a"), _f("b")])
        snap = _one(
            [
                _f("a", "ec2:snapshot", rec="Delete it."),
                _f("b", "rds:snapshot", rec="Delete it."),
            ]
        )

        assert any(
            "snapshot" in s.lower() or "back up" in s.lower()
            for s in vol["check_first"]
        )
        assert any(
            "restore" in s.lower() or "source" in s.lower() for s in snap["check_first"]
        )

    def test_rightsizing_asks_for_memory_evidence(self):
        opp = _one([_f("a", rec="Right-size it."), _f("b", rec="Right-size it.")])

        assert any("memory" in s.lower() for s in opp["check_first"])

    def test_review_asks_an_owner(self):
        opp = _one([_f("a", rec="Review"), _f("b", rec="Review")])

        assert any("owner" in s.lower() for s in opp["check_first"])
