from __future__ import annotations

from datetime import datetime, timezone

from core.models.finding import ResourceFinding
from core.remediation.engine import evaluate
from core.remediation.models import Condition, MetricCondition, Policy, ScopeFilter


def _finding(
    resource_id: str = "db-001",
    resource_type: str = "AWS::RDS::DBInstance",
    cloud: str = "aws",
    region: str = "us-east-1",
    cost: float = 200.0,
    priority: str = "high",
    last_activity: datetime | None = None,
    tags: dict | None = None,
    metrics_summary: dict | None = None,
    account_id: str = "123456",
) -> ResourceFinding:
    f = ResourceFinding(
        resource_id=resource_id,
        resource_type=resource_type,
        cloud=cloud,
        region=region,
        name=resource_id,
        estimated_monthly_cost=cost,
        waste_reason="Idle",
        recommendation="Resize",
        priority=priority,
        metrics_summary=metrics_summary or {},
        tags=tags or {},
        last_activity=last_activity,
        scan_time=datetime.now(tz=timezone.utc),
    )
    object.__setattr__(f, "account_id", account_id) if hasattr(
        f, "__dataclass_fields__"
    ) else None
    f.__dict__["account_id"] = account_id
    return f


def _policy(
    policy_id: str = "rds-resize",
    resource_type: str = "AWS::RDS::DBInstance",
    action: str = "resize",
    weight: int = 10,
    conditions: Condition | None = None,
    include: ScopeFilter | None = None,
    exclude: ScopeFilter | None = None,
) -> Policy:
    return Policy(
        policy_id=policy_id,
        name=f"Policy {policy_id}",
        resource_type=resource_type,
        conditions=conditions or Condition(),
        action=action,
        weight=weight,
        include=include or ScopeFilter(),
        exclude=exclude or ScopeFilter(),
        source_file="test.yaml",
    )


class TestEvaluateEmpty:
    def test_no_policies_returns_empty(self):
        findings = [_finding()]
        assert evaluate(findings, []) == []

    def test_no_findings_returns_empty(self):
        policies = [_policy()]
        assert evaluate([], policies) == []


class TestResourceTypeMatching:
    def test_matching_resource_type_produces_proposal(self):
        proposals = evaluate([_finding()], [_policy()])
        assert len(proposals) == 1

    def test_non_matching_resource_type_no_proposal(self):
        proposals = evaluate(
            [_finding(resource_type="AWS::EC2::Instance")],
            [_policy(resource_type="AWS::RDS::DBInstance")],
        )
        assert proposals == []

    def test_wildcard_resource_type_matches_all(self):
        proposals = evaluate(
            [_finding(resource_type="AWS::EC2::Instance")],
            [_policy(resource_type="*")],
        )
        assert len(proposals) == 1


class TestTier1Conditions:
    def test_cost_above_threshold_matches(self):
        cond = Condition(min_estimated_monthly_cost_usd=100.0)
        proposals = evaluate([_finding(cost=200.0)], [_policy(conditions=cond)])
        assert len(proposals) == 1

    def test_cost_below_threshold_no_match(self):
        cond = Condition(min_estimated_monthly_cost_usd=300.0)
        proposals = evaluate([_finding(cost=200.0)], [_policy(conditions=cond)])
        assert proposals == []

    def test_ai_priority_matches(self):
        cond = Condition(ai_priority=("high", "medium"))
        proposals = evaluate([_finding(priority="high")], [_policy(conditions=cond)])
        assert len(proposals) == 1

    def test_ai_priority_no_match(self):
        cond = Condition(ai_priority=("high",))
        proposals = evaluate([_finding(priority="low")], [_policy(conditions=cond)])
        assert proposals == []

    def test_idle_days_min_matches(self):
        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cond = Condition(idle_days_min=14)
        proposals = evaluate([_finding(last_activity=old)], [_policy(conditions=cond)])
        assert len(proposals) == 1

    def test_idle_days_min_recent_no_match(self):
        recent = datetime.now(tz=timezone.utc)
        cond = Condition(idle_days_min=14)
        proposals = evaluate(
            [_finding(last_activity=recent)], [_policy(conditions=cond)]
        )
        assert proposals == []

    def test_idle_days_min_no_activity_no_match(self):
        cond = Condition(idle_days_min=14)
        proposals = evaluate([_finding(last_activity=None)], [_policy(conditions=cond)])
        assert proposals == []


class TestScopeFilters:
    def test_include_cloud_matches(self):
        inc = ScopeFilter(cloud_platforms=("aws",))
        proposals = evaluate([_finding(cloud="aws")], [_policy(include=inc)])
        assert len(proposals) == 1

    def test_include_cloud_no_match(self):
        inc = ScopeFilter(cloud_platforms=("gcp",))
        proposals = evaluate([_finding(cloud="aws")], [_policy(include=inc)])
        assert proposals == []

    def test_include_region_matches(self):
        inc = ScopeFilter(regions=("us-east-1",))
        proposals = evaluate([_finding(region="us-east-1")], [_policy(include=inc)])
        assert len(proposals) == 1

    def test_include_region_no_match(self):
        inc = ScopeFilter(regions=("eu-west-1",))
        proposals = evaluate([_finding(region="us-east-1")], [_policy(include=inc)])
        assert proposals == []

    def test_exclude_region_skips_finding(self):
        exc = ScopeFilter(regions=("us-east-1",))
        proposals = evaluate([_finding(region="us-east-1")], [_policy(exclude=exc)])
        assert proposals == []

    def test_exclude_tag_skips_finding(self):
        exc = ScopeFilter(tags=({"do-not-touch": ["true"]},))
        proposals = evaluate(
            [_finding(tags={"do-not-touch": "true"})],
            [_policy(exclude=exc)],
        )
        assert proposals == []

    def test_include_tag_matches(self):
        inc = ScopeFilter(tags=({"environment": ["prod"]},))
        proposals = evaluate(
            [_finding(tags={"environment": "prod"})],
            [_policy(include=inc)],
        )
        assert len(proposals) == 1

    def test_include_tag_no_match(self):
        inc = ScopeFilter(tags=({"environment": ["prod"]},))
        proposals = evaluate(
            [_finding(tags={"environment": "dev"})],
            [_policy(include=inc)],
        )
        assert proposals == []


class TestWeightOrdering:
    def test_higher_weight_wins(self):
        low = _policy("low-weight", weight=5, action="stop")
        high = _policy("high-weight", weight=20, action="resize")
        proposals = evaluate([_finding()], [low, high])
        assert len(proposals) == 1
        assert proposals[0].policy.policy_id == "high-weight"
        assert proposals[0].policy.action == "resize"

    def test_first_match_stops_evaluation(self):
        # Both policies match but only the higher weight should fire
        p1 = _policy("p1", weight=20, action="resize")
        p2 = _policy("p2", weight=10, action="stop")
        proposals = evaluate([_finding()], [p1, p2])
        assert len(proposals) == 1
        assert proposals[0].policy.policy_id == "p1"

    def test_multiple_findings_each_matched_independently(self):
        rds = _finding("rds-001", resource_type="AWS::RDS::DBInstance")
        ec2 = _finding("ec2-001", resource_type="AWS::EC2::Instance")
        p_rds = _policy("rds-p", resource_type="AWS::RDS::DBInstance", action="resize")
        p_ec2 = _policy("ec2-p", resource_type="AWS::EC2::Instance", action="stop")
        proposals = evaluate([rds, ec2], [p_rds, p_ec2])
        assert len(proposals) == 2
        actions = {p.policy.action for p in proposals}
        assert actions == {"resize", "stop"}


class TestTier2Conditions:
    def test_metric_condition_passes(self):
        mc = MetricCondition(metric="CPUUtilization_avg", operator="lt", threshold=30.0)
        cond = Condition(metrics=(mc,))
        proposals = evaluate(
            [_finding(metrics_summary={"CPUUtilization_avg": 10.0})],
            [_policy(conditions=cond)],
        )
        assert len(proposals) == 1

    def test_metric_condition_fails(self):
        mc = MetricCondition(metric="CPUUtilization_avg", operator="lt", threshold=30.0)
        cond = Condition(metrics=(mc,))
        proposals = evaluate(
            [_finding(metrics_summary={"CPUUtilization_avg": 50.0})],
            [_policy(conditions=cond)],
        )
        assert proposals == []

    def test_missing_metric_skipped_not_blocking(self):
        # If metric not in metrics_summary, condition is skipped (not a blocker)
        mc = MetricCondition(metric="CPUUtilization_avg", operator="lt", threshold=30.0)
        cond = Condition(metrics=(mc,))
        proposals = evaluate(
            [_finding(metrics_summary={})],
            [_policy(conditions=cond)],
        )
        assert len(proposals) == 1

    def test_unknown_resource_type_skips_tier2(self):
        mc = MetricCondition(metric="SomeMetric", operator="lt", threshold=10.0)
        cond = Condition(metrics=(mc,))
        proposals = evaluate(
            [
                _finding(
                    resource_type="AWS::Unknown::Type",
                    metrics_summary={"SomeMetric": 5.0},
                )
            ],
            [_policy(resource_type="AWS::Unknown::Type", conditions=cond)],
        )
        # Unknown type → Tier 2 skipped → policy still matches via Tier 1
        assert len(proposals) == 1


class TestProposalContents:
    def test_proposal_has_correct_fields(self):
        proposals = evaluate([_finding(cost=340.0)], [_policy(action="resize")])
        assert len(proposals) == 1
        p = proposals[0]
        assert p.finding.resource_id == "db-001"
        assert p.policy.action == "resize"
        assert p.estimated_monthly_cost_usd == 340.0
        assert p.jira_ticket_url is None

    def test_proposal_to_dict(self):
        proposals = evaluate([_finding()], [_policy()])
        d = proposals[0].to_dict()
        assert d["resource_id"] == "db-001"
        assert d["policy_id"] == "rds-resize"
        assert d["action"] == "resize"
        assert "estimated_monthly_cost_usd" in d
        assert "runbook" in d
