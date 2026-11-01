"""
Grouping findings into opportunities: deterministic, no model, no cloud calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from core.models.finding import ResourceFinding
from core.opportunities.actions import classify_action, family_of
from core.opportunities.grouping import build_opportunities, opportunity_summary
from core.reports.generator import build_report
from core.reports.multi_cloud import merge_reports

SCAN_TIME = datetime(2026, 10, 30, 9, 0, 0, tzinfo=timezone.utc)


def _f(
    rid: str,
    rtype: str = "AWS::EC2::Volume",
    cost: float = 10.0,
    basis: str = "model_estimate",
    rec: str = "Delete the volume after a snapshot.",
    by: str = "model",
    conf: str = "high",
    priority: str = "medium",
    tags: dict[str, str] | None = None,
    review: bool = False,
    account: str = "111111111111",
    reason: str = "Idle.",
) -> dict[str, Any]:
    return {
        "resource_id": rid,
        "resource_type": rtype,
        "cloud": "aws",
        "region": "us-east-1",
        "account_id": account,
        "name": rid,
        "estimated_monthly_cost": cost,
        "cost_basis": basis,
        "recommendation": rec,
        "waste_reason": reason,
        "detected_by": by,
        "confidence": conf,
        "priority": priority,
        "tags": tags or {},
        "review_required": review,
        "review_reasons": ["prod_like_name"] if review else [],
        "metrics_summary": {"metrics": {"x": 1}},
    }


class TestClassifyAction:
    @pytest.mark.parametrize(
        "rec,expected",
        [
            ("Delete the volume.", "remove"),
            ("Terminate the instance.", "remove"),
            ("Release the address.", "remove"),
            ("Snapshot it, then delete the volume.", "remove"),
            ("Stop the instance outside business hours.", "stop"),
            ("Right-size to db.t3.small.", "rightsize"),
            ("Downsize the node group.", "rightsize"),
            ("Set a 30 day retention on the log group.", "retention"),
            ("Add a lifecycle rule.", "retention"),
            ("Review and delete if no longer needed.", "review"),
            ("Verify with the owner before removing.", "review"),
            ("Investigate the connections.", "review"),
            ("", "review"),
            (None, "review"),
        ],
    )
    def test_first_meaningful_verb_decides(self, rec, expected):
        assert classify_action({"recommendation": rec}) == expected

    def test_deterministic_rules_are_removals(self):
        f = {"recommendation": "Review.", "detected_by": "rule:ebs-volume-unattached"}

        assert classify_action(f) == "remove"


class TestFamily:
    def test_all_snapshot_types_share_a_family(self):
        fams = {
            family_of(t)
            for t in ("ec2:snapshot", "rds:snapshot", "rds:cluster-snapshot")
        }

        assert fams == {"snapshot"}

    def test_other_types_keep_their_own_family(self):
        assert family_of("AWS::EC2::Volume") == "AWS::EC2::Volume"


class TestPartition:
    def test_every_finding_lands_in_exactly_one_opportunity(self):
        findings = [_f(f"vol-{i}") for i in range(5)] + [
            _f(f"eip-{i}", "AWS::EC2::EIP", rec="Release it.") for i in range(3)
        ]

        opps = build_opportunities(findings)
        members = [m for o in opps for m in o["members"]]

        assert sorted(members) == sorted(f["resource_id"] for f in findings)
        assert len(set(members)) == len(members)

    def test_member_counts_add_up(self):
        findings = [_f(f"vol-{i}") for i in range(4)]

        opps = build_opportunities(findings)

        assert sum(o["member_count"] for o in opps) == 4

    def test_savings_high_equals_the_total_of_priced_findings(self):
        findings = [
            _f("a", cost=100.0, basis="billed"),
            _f("b", cost=40.0, basis="list_price"),
            _f("c", cost=860.0),
            _f("d", cost=0.0, basis="unknown"),
        ]

        opps = build_opportunities(findings)

        assert sum(o["savings"]["high_usd"] for o in opps) == pytest.approx(1000.0)

    def test_empty_input_gives_no_opportunities(self):
        assert build_opportunities([]) == []


class TestSplitting:
    def test_findings_that_need_review_are_kept_apart(self):
        findings = [
            _f("a"),
            _f("b"),
            _f("p1", review=True),
            _f("p2", review=True),
        ]

        opps = build_opportunities(findings)

        assert len(opps) == 2
        risky = [o for o in opps if o["review_required_count"]]
        safe = [o for o in opps if not o["review_required_count"]]
        assert risky[0]["members"] == ["p1", "p2"] or set(risky[0]["members"]) == {
            "p1",
            "p2",
        }
        assert set(safe[0]["members"]) == {"a", "b"}

    def test_different_actions_on_one_type_are_separate_opportunities(self):
        findings = [
            _f("a", rec="Delete it."),
            _f("b", rec="Delete it."),
            _f("c", rec="Right-size it."),
            _f("d", rec="Right-size it."),
        ]

        opps = build_opportunities(findings)

        assert {o["action"] for o in opps} == {"remove", "rightsize"}

    def test_owner_does_not_split_a_group(self):
        findings = [
            _f("a", tags={"Team": "x"}),
            _f("b", tags={"Team": "y"}),
            _f("c"),
        ]

        opps = build_opportunities(findings)

        assert len(opps) == 1
        assert {o["tag"] + "=" + o["value"] for o in opps[0]["owners"]} == {
            "team=x",
            "team=y",
        }


class TestTiers:
    def test_unsure_members_are_split_from_confident_ones(self):
        findings = [
            _f("a", conf="high"),
            _f("b", conf="medium"),
            _f("c", conf="low"),
            _f("d", conf="low"),
        ]

        opps = build_opportunities(findings)

        by_tier = {o["key"]["tier"]: o for o in opps}
        assert set(by_tier) == {"sure", "unsure"}
        assert set(by_tier["sure"]["members"]) == {"a", "b"}
        assert by_tier["sure"]["lane"] == "easy"
        assert by_tier["unsure"]["lane"] == "doubt"

    def test_a_flagged_finding_is_flagged_whatever_its_confidence(self):
        findings = [_f("a", review=True, conf="high"), _f("b", review=True, conf="low")]

        (opp,) = build_opportunities(findings)

        assert opp["key"]["tier"] == "flagged"
        assert opp["lane"] == "doubt"

    def test_a_missing_confidence_counts_as_unsure(self):
        findings = [_f("a", conf=None), _f("b", conf=None)]

        (opp,) = build_opportunities(findings)

        assert opp["key"]["tier"] == "unsure"


class TestSmallGroups:
    def _mixed(self):
        big = [_f(f"vol-{i}") for i in range(3)]
        singles = [
            _f("n1", "AWS::EC2::NatGateway"),
            _f("l1", "AWS::ElasticLoadBalancingV2::LoadBalancer"),
            _f("q1", "AWS::SQS::Queue"),
        ]
        return big + singles

    def test_groups_below_the_minimum_collapse_into_one_other_bucket(self):
        opps = build_opportunities(self._mixed(), min_group_size=2)

        other = [o for o in opps if o["key"]["family"] == "other"]
        assert len(other) == 1
        assert other[0]["member_count"] == 3
        assert "other resources" in other[0]["title"]

    def test_the_other_bucket_is_per_action_and_tier(self):
        findings = self._mixed() + [_f("n2", "AWS::EC2::EIP", rec="Review it.")]

        opps = build_opportunities(findings, min_group_size=2)

        others = [o for o in opps if o["key"]["family"] == "other"]
        assert {o["action"] for o in others} == {"remove", "review"}

    def test_a_cap_raises_the_minimum_until_the_count_fits(self):
        findings = []
        for t in range(30):
            findings += [_f(f"t{t}-a", f"x:type{t}"), _f(f"t{t}-b", f"x:type{t}")]

        uncapped = build_opportunities(findings, min_group_size=2, max_opportunities=0)
        capped = build_opportunities(findings, min_group_size=2, max_opportunities=10)

        assert len(uncapped) == 30
        assert len(capped) <= 10
        assert sum(o["member_count"] for o in capped) == 60


class TestSavingsAndRisk:
    def test_range_is_deterministic_dollars_up_to_adding_model_estimates(self):
        findings = [
            _f("a", cost=100.0, basis="billed"),
            _f("b", cost=40.0, basis="list_price"),
            _f("c", cost=860.0, basis="model_estimate"),
            _f("d", cost=0.0, basis="unknown"),
        ]

        (opp,) = build_opportunities(findings)

        assert opp["savings"]["low_usd"] == 140.0
        assert opp["savings"]["high_usd"] == 1000.0
        assert opp["savings"]["unpriced"] == 1
        assert opp["savings"]["by_basis"]["model_estimate"] == 860.0

    def test_priority_is_the_highest_and_confidence_the_lowest(self):
        findings = [
            _f("a", priority="low", conf="high"),
            _f("b", priority="high", conf="medium"),
        ]

        (opp,) = build_opportunities(findings)

        assert opp["priority"] == "high"
        assert opp["confidence"] == "medium"

    def test_risk_reasons_are_collected(self):
        (opp,) = build_opportunities([_f("a", review=True), _f("b", review=True)])

        assert opp["review_required_count"] == 2
        assert opp["risk_reasons"] == ["prod_like_name"]


class TestLanes:
    def test_clear_removals_are_easy(self):
        (opp,) = build_opportunities([_f("a"), _f("b")])

        assert opp["lane"] == "easy"

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"rec": "Review it."},
            {"rec": "Right-size it."},
            {"conf": "low"},
            {"review": True},
        ],
    )
    def test_uncertain_or_risky_items_need_an_owner(self, kwargs):
        (opp,) = build_opportunities([_f("a", **kwargs), _f("b", **kwargs)])

        assert opp["lane"] == "doubt"

    def test_easy_opportunities_are_listed_before_doubtful_ones(self):
        findings = [
            _f("a", cost=500.0, rec="Review it."),
            _f("b", cost=500.0, rec="Review it."),
            _f("c", cost=1.0),
            _f("d", cost=1.0),
        ]

        opps = build_opportunities(findings)

        assert [o["lane"] for o in opps] == ["easy", "doubt"]


class TestIdentity:
    def test_the_id_is_stable_across_scans(self):
        one = build_opportunities([_f("a", cost=10.0), _f("b", cost=20.0)])
        two = build_opportunities([_f("c", cost=99.0), _f("d", cost=1.0)])

        assert one[0]["id"] == two[0]["id"]
        assert one[0]["id"].startswith("opp-")

    def test_the_id_changes_with_the_action(self):
        remove = build_opportunities([_f("a"), _f("b")])
        review = build_opportunities([_f("a", rec="Review"), _f("b", rec="Review")])

        assert remove[0]["id"] != review[0]["id"]

    def test_output_is_independent_of_input_order(self):
        findings = [_f(f"vol-{i}", cost=float(i)) for i in range(6)]

        a = build_opportunities(findings)
        b = build_opportunities(list(reversed(findings)))

        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_members_are_listed_by_cost_then_id(self):
        findings = [_f("b", cost=5.0), _f("a", cost=5.0), _f("c", cost=9.0)]

        (opp,) = build_opportunities(findings)

        assert opp["members"] == ["c", "a", "b"]


class TestTitles:
    def test_title_names_the_action_count_and_type(self):
        (opp,) = build_opportunities([_f(f"v{i}") for i in range(3)])

        assert opp["title"] == "Remove 3 EBS Volumes"

    def test_native_type_ids_are_made_readable(self):
        findings = [
            _f("l1", "logs:log-group", rec="Set a retention."),
            _f("l2", "logs:log-group", rec="Set a retention."),
        ]

        (opp,) = build_opportunities(findings)

        assert opp["title"] == "Set retention on 2 CloudWatch log groups"

    def test_snapshot_family_title_is_generic(self):
        findings = [
            _f("s1", "ec2:snapshot", rec="Delete it."),
            _f("s2", "rds:snapshot", rec="Delete it."),
        ]

        (opp,) = build_opportunities(findings)

        assert opp["title"] == "Remove 2 snapshots"


class TestReadableTypeNames:
    @pytest.mark.parametrize(
        "type_id,expected",
        [
            ("ec2:client-vpn-endpoint", "Remove 2 EC2 client VPN endpoints"),
            ("logs:log-group", "Remove 2 CloudWatch log groups"),
            ("amplify:apps/branches", "Remove 2 Amplify apps branches"),
            ("secretsmanager:secret", "Remove 2 Secrets Manager secrets"),
            ("AWS::EC2::EIP", "Remove 2 EC2 EIPs"),
        ],
    )
    def test_native_ids_read_like_names(self, type_id, expected):
        findings = [_f("a", type_id), _f("b", type_id)]

        (opp,) = build_opportunities(findings)

        assert opp["title"] == expected


class TestRelated:
    def test_a_finding_that_mentions_another_links_their_opportunities(self):
        findings = [
            _f("vol-0abc123", reason="Detached."),
            _f("vol-0abc124", reason="Detached."),
            _f(
                "i-0def456",
                "AWS::EC2::Instance",
                rec="Terminate it.",
                reason="Stopped; its disk vol-0abc123 still bills.",
            ),
            _f("i-0def457", "AWS::EC2::Instance", rec="Terminate it."),
        ]

        opps = {o["key"]["family"]: o for o in build_opportunities(findings)}

        vol, inst = opps["AWS::EC2::Volume"], opps["AWS::EC2::Instance"]
        assert inst["id"] in vol["related"]
        assert vol["id"] in inst["related"]

    def test_unrelated_opportunities_have_no_links(self):
        opps = build_opportunities([_f("a"), _f("b")])

        assert opps[0]["related"] == []


class TestOwners:
    def test_tag_priority_is_team_then_owner_then_project(self):
        findings = [
            _f("a", tags={"Project": "p", "Owner": "o"}),
            _f("b", tags={"Project": "p", "Owner": "o", "Team": "t"}),
        ]

        (opp,) = build_opportunities(findings)

        values = {(o["tag"], o["value"]): o["count"] for o in opp["owners"]}
        assert values == {("owner", "o"): 1, ("team", "t"): 1}

    def test_untagged_findings_are_counted_as_unowned(self):
        (opp,) = build_opportunities([_f("a"), _f("b")])

        assert opp["unowned_count"] == 2


class TestReportIntegration:
    def _findings(self) -> list[ResourceFinding]:
        out = []
        for i in range(4):
            out.append(
                ResourceFinding(
                    resource_id=f"vol-{i}",
                    resource_type="AWS::EC2::Volume",
                    cloud="aws",
                    region="us-east-1",
                    estimated_monthly_cost=10.0 + i,
                    waste_reason="Unattached.",
                    recommendation="Delete after a snapshot.",
                    priority="medium",
                    metrics_summary={"metrics": {"x": 1}},
                    tags={},
                    scan_time=SCAN_TIME,
                    name=f"vol-{i}",
                    cost_basis="list_price",
                    confidence="high",
                    detected_by="rule:ebs-volume-unattached",
                )
            )
        return out

    def test_build_report_carries_opportunities_and_a_summary(self):
        report = build_report(self._findings(), cloud="aws", executive_summary="x")

        assert len(report["opportunities"]) == 1
        assert report["opportunity_summary"]["findings"] == 4
        assert report["opportunity_summary"]["opportunities"] == 1
        assert report["opportunity_summary"]["reduction_ratio"] == 4.0

    def test_opportunity_totals_match_the_report_total(self):
        report = build_report(self._findings(), cloud="aws", executive_summary="x")

        total = sum(o["savings"]["high_usd"] for o in report["opportunities"])

        assert total == pytest.approx(report["total_estimated_waste_usd"])

    def test_an_empty_report_has_no_opportunities_and_no_ratio(self):
        report = build_report([], cloud="aws", executive_summary="x")

        assert report["opportunities"] == []
        assert report["opportunity_summary"]["reduction_ratio"] is None

    def test_merged_reports_regroup_all_findings(self):
        a = build_report(self._findings(), cloud="aws", executive_summary="a")
        b = build_report(self._findings(), cloud="aws", executive_summary="b")
        for f in b["findings"]:
            f["resource_id"] = "other-" + f["resource_id"]

        merged = merge_reports([a, b])

        assert merged["opportunity_summary"]["findings"] == 8
        assert sum(o["member_count"] for o in merged["opportunities"]) == 8


class TestSummary:
    def test_summary_reports_counts_lanes_and_ratio(self):
        findings = [_f("a"), _f("b"), _f("c", rec="Review"), _f("d", rec="Review")]

        s = opportunity_summary(findings, build_opportunities(findings))

        assert s["findings"] == 4
        assert s["opportunities"] == 2
        assert s["lanes"] == {"easy": 1, "doubt": 1}
        assert s["reduction_ratio"] == 2.0
        assert s["min_group_size"] == 2


class TestCli:
    def _report(self, tmp_path, findings):
        path = tmp_path / "report.json"
        path.write_text(json.dumps({"findings": findings}))
        return path

    def test_summary_prints_counts_lanes_and_reduction_without_titles(
        self, tmp_path, capsys
    ):
        from core.opportunities.__main__ import main

        findings = [
            _f("a"),
            _f("b"),
            _f("c", rec="Review it."),
            _f("d", rec="Review it."),
        ]

        code = main(["summary", "--report", str(self._report(tmp_path, findings))])

        out = capsys.readouterr().out
        assert code == 0
        assert "findings: 4" in out and "opportunities: 2" in out
        assert "reduction: 2.0x" in out
        assert "easy: 1" in out and "doubt: 1" in out
        assert "Remove 2" not in out

    def test_list_flag_adds_titles(self, tmp_path, capsys):
        from core.opportunities.__main__ import main

        report = self._report(tmp_path, [_f("a"), _f("b")])

        main(["summary", "--report", str(report), "--list", "5"])

        assert "Remove 2 EBS Volumes" in capsys.readouterr().out

    def test_min_group_size_and_cap_are_options(self, tmp_path, capsys):
        from core.opportunities.__main__ import main

        findings = [_f("a"), _f("b", "AWS::EC2::EIP"), _f("c", "AWS::SQS::Queue")]

        main(
            ["summary", "--report", str(self._report(tmp_path, findings))]
            + ["--min-group-size", "2"]
        )

        assert "opportunities: 1" in capsys.readouterr().out
