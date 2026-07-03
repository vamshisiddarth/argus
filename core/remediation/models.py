from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.models.finding import ResourceFinding

_VALID_OPERATORS = frozenset({"lt", "gt", "lte", "gte", "eq"})
_VALID_PRIORITIES = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class MetricCondition:
    metric: str
    operator: str  # lt | gt | lte | gte | eq
    threshold: float

    def __post_init__(self) -> None:
        if self.operator not in _VALID_OPERATORS:
            raise ValueError(
                f"Invalid operator '{self.operator}'. "
                f"Must be one of: {sorted(_VALID_OPERATORS)}"
            )
        if not self.metric:
            raise ValueError("metric must not be empty")

    def evaluate(self, value: float) -> bool:
        match self.operator:
            case "lt":
                return value < self.threshold
            case "gt":
                return value > self.threshold
            case "lte":
                return value <= self.threshold
            case "gte":
                return value >= self.threshold
            case "eq":
                return value == self.threshold
            case _:
                return False


@dataclass(frozen=True)
class Condition:
    # Tier 1 — universal, work on every resource type
    min_estimated_monthly_cost_usd: float | None = None
    ai_priority: tuple[str, ...] | None = None  # ("high", "medium")
    idle_days_min: int | None = None

    # Tier 2 — registry-known types only
    metrics: tuple[MetricCondition, ...] = ()

    def __post_init__(self) -> None:
        if self.ai_priority is not None:
            unknown = set(self.ai_priority) - _VALID_PRIORITIES
            if unknown:
                raise ValueError(
                    f"Unknown ai_priority values: {unknown}. "
                    f"Must be subset of: {sorted(_VALID_PRIORITIES)}"
                )


@dataclass(frozen=True)
class ScopeFilter:
    """
    Defines which resources a policy includes or excludes.

    tags is a list of single-key dicts for readable YAML:
      tags:
        - environment: [prod, staging]
        - team: [platform]
    """

    cloud_platforms: tuple[str, ...] | None = None  # None = all
    accounts: tuple[str, ...] | None = None  # None = all
    regions: tuple[str, ...] | None = None  # None = all
    tags: tuple[dict[str, list[str]], ...] = ()  # empty = all


@dataclass(frozen=True)
class Policy:
    policy_id: str
    name: str
    resource_type: str  # "AWS::RDS::DBInstance" or "*"
    conditions: Condition
    action: str  # from registry _VALID_ACTIONS
    approvers: tuple[dict[str, str], ...]  # ({"group": "platform-team"}, ...)
    weight: int = 0
    include: ScopeFilter = field(default_factory=ScopeFilter)
    exclude: ScopeFilter = field(default_factory=ScopeFilter)
    source_file: str = ""  # set by loader

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")
        if not self.resource_type:
            raise ValueError("resource_type must not be empty")
        if not self.action:
            raise ValueError("action must not be empty")


@dataclass
class ChangeProposal:
    finding: ResourceFinding
    policy: Policy
    runbook: str
    estimated_saving_usd: float
    jira_ticket_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.finding.resource_id,
            "resource_type": self.finding.resource_type,
            "policy_id": self.policy.policy_id,
            "action": self.policy.action,
            "estimated_saving_usd": round(self.estimated_saving_usd, 2),
            "runbook": self.runbook,
            "jira_ticket_url": self.jira_ticket_url,
        }
