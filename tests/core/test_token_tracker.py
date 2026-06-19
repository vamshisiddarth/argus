from __future__ import annotations

import pytest

from core.token_tracker import BudgetExceededError, TokenTracker


class TestTokenTracker:
    def test_record_accumulates_tokens(self):
        tracker = TokenTracker(budget_usd=10.0)
        tracker.record(1000, 500)
        tracker.record(2000, 1000)

        assert tracker.total_input_tokens == 3000
        assert tracker.total_output_tokens == 1500
        assert tracker.iteration_count == 2

    def test_estimated_cost_anthropic(self):
        tracker = TokenTracker(budget_usd=10.0, provider="anthropic")
        tracker.record(1_000_000, 100_000)
        # 1M input * $3/M + 100K output * $15/M = $3 + $1.5 = $4.5
        assert tracker.estimated_cost_usd == 4.5

    def test_estimated_cost_vertexai(self):
        tracker = TokenTracker(budget_usd=10.0, provider="vertexai")
        tracker.record(1_000_000, 1_000_000)
        # 1M * $1.25 + 1M * $5.0 = $6.25
        assert tracker.estimated_cost_usd == 6.25

    def test_estimated_cost_azure_openai(self):
        tracker = TokenTracker(budget_usd=0, provider="azure_openai")
        tracker.record(1_000_000, 1_000_000)
        # 1M * $2.50 + 1M * $10.0 = $12.50
        assert tracker.estimated_cost_usd == 12.5

    def test_unknown_provider_uses_default_pricing(self):
        tracker = TokenTracker(budget_usd=10.0, provider="unknown_provider")
        tracker.record(1_000_000, 0)
        # Default: $3/M input
        assert tracker.estimated_cost_usd == 3.0

    def test_budget_exceeded_raises(self):
        tracker = TokenTracker(budget_usd=0.01)
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.record(1_000_000, 1_000_000)

        assert exc_info.value.spent_usd > 0.01
        assert exc_info.value.budget_usd == 0.01

    def test_budget_zero_means_unlimited(self):
        tracker = TokenTracker(budget_usd=0)
        tracker.record(10_000_000, 10_000_000)
        # No exception raised — budget=0 disables enforcement
        assert tracker.iteration_count == 1

    def test_budget_not_exceeded_no_raise(self):
        tracker = TokenTracker(budget_usd=100.0)
        tracker.record(1000, 500)
        assert tracker.iteration_count == 1

    def test_summary(self):
        tracker = TokenTracker(budget_usd=5.0, provider="bedrock")
        tracker.record(100, 200)
        tracker.record(300, 400)

        summary = tracker.summary()
        assert summary["total_input_tokens"] == 400
        assert summary["total_output_tokens"] == 600
        assert summary["iterations"] == 2
        assert summary["budget_usd"] == 5.0
        assert isinstance(summary["estimated_cost_usd"], float)

    def test_per_iteration_tracking(self):
        tracker = TokenTracker(budget_usd=10.0)
        tracker.record(100, 50)
        tracker.record(200, 100)

        assert len(tracker._per_iteration) == 2
        assert tracker._per_iteration[0] == {"input": 100, "output": 50}
        assert tracker._per_iteration[1] == {"input": 200, "output": 100}

    def test_budget_exceeded_on_cumulative_not_single(self):
        # Budget allows ~333 input tokens at $3/M + $15/M pricing
        tracker = TokenTracker(budget_usd=0.01, provider="anthropic")
        # First call: small, under budget
        tracker.record(100, 50)
        # Second call: still under individually but cumulative pushes over
        with pytest.raises(BudgetExceededError):
            tracker.record(1_000_000, 100_000)


class TestBudgetExceededError:
    def test_error_message(self):
        err = BudgetExceededError(spent_usd=5.1234, budget_usd=5.0)
        assert "$5.1234 spent" in str(err)
        assert "$5.00" in str(err)

    def test_attributes(self):
        err = BudgetExceededError(spent_usd=3.0, budget_usd=2.0)
        assert err.spent_usd == 3.0
        assert err.budget_usd == 2.0
