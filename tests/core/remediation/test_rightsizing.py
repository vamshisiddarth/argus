"""Tests for core.remediation.rightsizing heuristics."""

from __future__ import annotations

from datetime import datetime, timezone

from core.models.finding import ResourceFinding
from core.remediation.models import Condition, Policy, ScopeFilter
from core.remediation.rightsizing import suggest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _finding(
    resource_type: str = "AWS::RDS::DBInstance",
    metrics: dict | None = None,
) -> ResourceFinding:
    return ResourceFinding(
        resource_id="db-1",
        resource_type=resource_type,
        cloud="aws",
        region="us-east-1",
        name="test-db",
        estimated_monthly_cost=120.0,
        waste_reason="idle",
        recommendation="resize",
        priority="high",
        metrics_summary=metrics or {},
        tags={},
        last_activity=datetime(2026, 1, 1, tzinfo=timezone.utc),
        scan_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def _policy(action: str = "resize") -> Policy:
    return Policy(
        policy_id="rds-resize",
        name="Resize idle RDS",
        resource_type="AWS::RDS::DBInstance",
        action=action,
        weight=20,
        conditions=Condition(),
        include=ScopeFilter(),
        exclude=ScopeFilter(),
        source_file="rds.yaml",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuggestNotApplicable:
    def test_stop_action_returns_none(self):
        assert suggest(_finding(), _policy(action="stop")) is None

    def test_delete_action_returns_none(self):
        assert suggest(_finding(), _policy(action="delete")) is None

    def test_resize_no_metrics_returns_none(self):
        assert suggest(_finding(metrics={}), _policy()) is None


class TestRDSResize:
    def test_very_low_cpu_recommends_micro(self):
        rec = suggest(_finding(metrics={"CPUUtilization_avg": 2.0}), _policy())
        assert rec is not None
        assert "db.t3.micro" in rec

    def test_low_cpu_recommends_small(self):
        rec = suggest(_finding(metrics={"CPUUtilization_avg": 10.0}), _policy())
        assert rec is not None
        assert "db.t3.small" in rec

    def test_medium_cpu_recommends_medium(self):
        rec = suggest(_finding(metrics={"CPUUtilization_avg": 20.0}), _policy())
        assert rec is not None
        assert "db.t3.medium" in rec

    def test_high_cpu_returns_review_message(self):
        rec = suggest(_finding(metrics={"CPUUtilization_avg": 70.0}), _policy())
        assert rec is not None
        assert "review" in rec.lower()

    def test_includes_observed_cpu_in_message(self):
        rec = suggest(_finding(metrics={"CPUUtilization_avg": 4.5}), _policy())
        assert rec is not None
        assert "4.5" in rec


class TestEC2Resize:
    def _ec2_policy(self) -> Policy:
        return Policy(
            policy_id="ec2-stop",
            name="Stop idle EC2",
            resource_type="AWS::EC2::Instance",
            action="resize",
            weight=20,
            conditions=Condition(),
            include=ScopeFilter(),
            exclude=ScopeFilter(),
            source_file="ec2.yaml",
        )

    def _ec2_finding(self, cpu: float) -> ResourceFinding:
        return _finding(
            resource_type="AWS::EC2::Instance",
            metrics={"CPUUtilization_avg": cpu},
        )

    def test_very_low_cpu_recommends_nano_or_micro(self):
        rec = suggest(self._ec2_finding(1.0), self._ec2_policy())
        assert rec is not None
        assert "t3.nano" in rec or "t3.micro" in rec

    def test_low_cpu_recommends_small(self):
        rec = suggest(self._ec2_finding(7.0), self._ec2_policy())
        assert rec is not None
        assert "t3.small" in rec

    def test_medium_cpu_recommends_medium(self):
        rec = suggest(self._ec2_finding(20.0), self._ec2_policy())
        assert rec is not None
        assert "t3.medium" in rec


class TestNodeReduction:
    def _cluster_finding(self, cpu: float, nodes: int | None = None) -> ResourceFinding:
        metrics: dict = {"kubernetes.io/container/cpu/request_utilization": cpu}
        if nodes is not None:
            metrics["node_count"] = nodes
        return _finding(
            resource_type="container.googleapis.com/Cluster",
            metrics=metrics,
        )

    def _cluster_policy(self) -> Policy:
        return Policy(
            policy_id="gke-reduce",
            name="Reduce GKE nodes",
            resource_type="container.googleapis.com/Cluster",
            action="reduce_nodes",
            weight=20,
            conditions=Condition(),
            include=ScopeFilter(),
            exclude=ScopeFilter(),
            source_file="gke.yaml",
        )

    def test_low_cpu_with_nodes_suggests_fewer(self):
        rec = suggest(self._cluster_finding(10.0, nodes=10), self._cluster_policy())
        assert rec is not None
        assert "nodes" in rec.lower() or "node" in rec.lower()

    def test_recommendation_does_not_suggest_more_nodes_than_current(self):
        rec = suggest(self._cluster_finding(8.0, nodes=5), self._cluster_policy())
        if rec is not None:
            # Extract any number mentioned after "reducing to"
            import re
            match = re.search(r"reducing to (\d+)", rec)
            if match:
                assert int(match.group(1)) < 5

    def test_no_nodes_metric_returns_generic(self):
        rec = suggest(self._cluster_finding(5.0, nodes=None), self._cluster_policy())
        assert rec is not None
        assert "node" in rec.lower()

    def test_high_cpu_no_suggestion(self):
        rec = suggest(self._cluster_finding(80.0, nodes=5), self._cluster_policy())
        assert rec is None


class TestFallbackCPUKey:
    def test_recognises_generic_cpu_key(self):
        finding = _finding(
            resource_type="AWS::RDS::DBInstance",
            metrics={"avg_cpu_percent": 3.0},
        )
        rec = suggest(finding, _policy())
        assert rec is not None
        assert "3.0" in rec
