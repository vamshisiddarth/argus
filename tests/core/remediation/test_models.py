from __future__ import annotations

import pytest

from core.remediation.models import Condition, MetricCondition, Policy, ScopeFilter


class TestMetricCondition:
    def test_valid_operators(self):
        for op in ("lt", "gt", "lte", "gte", "eq"):
            mc = MetricCondition(
                metric="CPUUtilization_avg", operator=op, threshold=30.0
            )
            assert mc.operator == op

    def test_invalid_operator_raises(self):
        with pytest.raises(ValueError, match="Invalid operator"):
            MetricCondition(metric="CPUUtilization_avg", operator="neq", threshold=30.0)

    def test_empty_metric_raises(self):
        with pytest.raises(ValueError, match="metric must not be empty"):
            MetricCondition(metric="", operator="lt", threshold=30.0)

    def test_evaluate_lt(self):
        mc = MetricCondition(metric="CPU", operator="lt", threshold=30.0)
        assert mc.evaluate(20.0) is True
        assert mc.evaluate(30.0) is False
        assert mc.evaluate(40.0) is False

    def test_evaluate_gt(self):
        mc = MetricCondition(metric="CPU", operator="gt", threshold=30.0)
        assert mc.evaluate(40.0) is True
        assert mc.evaluate(30.0) is False

    def test_evaluate_lte(self):
        mc = MetricCondition(metric="CPU", operator="lte", threshold=30.0)
        assert mc.evaluate(30.0) is True
        assert mc.evaluate(29.9) is True
        assert mc.evaluate(30.1) is False

    def test_evaluate_gte(self):
        mc = MetricCondition(metric="CPU", operator="gte", threshold=30.0)
        assert mc.evaluate(30.0) is True
        assert mc.evaluate(31.0) is True
        assert mc.evaluate(29.9) is False

    def test_evaluate_eq(self):
        mc = MetricCondition(metric="CPU", operator="eq", threshold=30.0)
        assert mc.evaluate(30.0) is True
        assert mc.evaluate(30.1) is False


class TestCondition:
    def test_valid_ai_priority(self):
        cond = Condition(ai_priority=("high", "medium"))
        assert cond.ai_priority == ("high", "medium")

    def test_invalid_ai_priority_raises(self):
        with pytest.raises(ValueError, match="Unknown ai_priority"):
            Condition(ai_priority=("critical",))

    def test_all_none_defaults(self):
        cond = Condition()
        assert cond.min_estimated_monthly_cost_usd is None
        assert cond.ai_priority is None
        assert cond.idle_days_min is None
        assert cond.metrics == ()


class TestScopeFilter:
    def test_defaults_all_none(self):
        sf = ScopeFilter()
        assert sf.cloud_platforms is None
        assert sf.accounts is None
        assert sf.regions is None
        assert sf.tags == ()

    def test_tags_list_of_dicts(self):
        sf = ScopeFilter(tags=({"environment": ["prod", "staging"]},))
        assert sf.tags[0] == {"environment": ["prod", "staging"]}


class TestPolicy:
    def _make(self, **kwargs) -> Policy:
        defaults = dict(
            policy_id="test-policy",
            name="Test Policy",
            resource_type="AWS::RDS::DBInstance",
            conditions=Condition(),
            action="resize",
            approvers=("platform-team",),
            weight=10,
        )
        defaults.update(kwargs)
        return Policy(**defaults)

    def test_valid_policy(self):
        p = self._make()
        assert p.policy_id == "test-policy"
        assert p.action == "resize"

    def test_empty_policy_id_raises(self):
        with pytest.raises(ValueError, match="policy_id"):
            self._make(policy_id="")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            self._make(name="")

    def test_empty_resource_type_raises(self):
        with pytest.raises(ValueError, match="resource_type"):
            self._make(resource_type="")

    def test_empty_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            self._make(action="")
