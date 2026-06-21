"""
LLM token and cost tracking with hard budget enforcement.

Tracks cumulative input/output tokens across agent iterations and estimates
USD cost using per-provider pricing. When ``LLM_BUDGET_USD`` is exceeded,
raises ``BudgetExceededError`` so the agent loop can abort gracefully and
still return partial findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Per-million-token pricing (input, output) by provider.
# Updated 2025-05 — check provider pricing pages for current rates.
_PRICING: dict[str, tuple[float, float]] = {
    "anthropic": (3.0, 15.0),
    "bedrock": (3.0, 15.0),
    "vertexai": (1.25, 5.0),
    "azure_openai": (2.50, 10.0),
}

_DEFAULT_PRICING = (3.0, 15.0)


class BudgetExceededError(Exception):
    """Raised when cumulative LLM cost exceeds the configured budget."""

    def __init__(self, spent_usd: float, budget_usd: float) -> None:
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd
        super().__init__(
            f"LLM budget exceeded: ${spent_usd:.4f} spent "
            f"(budget: ${budget_usd:.2f})"
        )


@dataclass
class TokenTracker:
    """Accumulates token usage and enforces a hard USD budget."""

    budget_usd: float
    provider: str = "anthropic"

    total_input_tokens: int = field(default=0, init=False)
    total_output_tokens: int = field(default=0, init=False)
    iteration_count: int = field(default=0, init=False)
    _per_iteration: list[dict[str, int]] = field(default_factory=list, init=False)

    def record(self, input_tokens: int, output_tokens: int) -> None:
        """
        Record tokens from one AI call and check the budget.

        Raises ``BudgetExceededError`` if cumulative cost exceeds budget.
        """
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.iteration_count += 1
        self._per_iteration.append({"input": input_tokens, "output": output_tokens})

        spent = self.estimated_cost_usd
        logger.info(
            "token_usage",
            iteration=self.iteration_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cumulative_input=self.total_input_tokens,
            cumulative_output=self.total_output_tokens,
            spent_usd=round(spent, 4),
            budget_usd=self.budget_usd,
        )

        if self.budget_usd > 0 and spent > self.budget_usd:
            raise BudgetExceededError(round(spent, 4), self.budget_usd)

    @property
    def estimated_cost_usd(self) -> float:
        input_rate, output_rate = _PRICING.get(self.provider, _DEFAULT_PRICING)
        cost = (self.total_input_tokens / 1_000_000 * input_rate) + (
            self.total_output_tokens / 1_000_000 * output_rate
        )
        return round(cost, 4)

    def summary(self) -> dict[str, float | int]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "iterations": self.iteration_count,
            "estimated_cost_usd": self.estimated_cost_usd,
            "budget_usd": self.budget_usd,
        }
