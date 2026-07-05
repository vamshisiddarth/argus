from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Resource:
    """Minimal representation of a discovered cloud resource."""

    resource_id: str
    resource_type: str  # e.g. "AWS::EC2::Instance"
    cloud: str  # "aws" | "gcp" | "azure"
    region: str
    name: str | None = None
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "cloud": self.cloud,
            "region": self.region,
            "name": self.name,
            "tags": self.tags,
        }


@dataclass
class MetricSummary:
    """Key usage metrics for a resource over a lookback window."""

    resource_id: str
    resource_type: str
    period_days: int
    metrics: dict[str, Any]  # {"avg_cpu_pct": 1.2, "network_bytes_total": 847, ...}
    has_data: bool = True  # False if CloudWatch has no data points

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "period_days": self.period_days,
            "metrics": self.metrics,
            "has_data": self.has_data,
        }


class CloudAdapter(ABC):
    """
    Abstract cloud adapter. One implementation per cloud provider.
    The agent loop only ever calls these four methods — never raw SDK clients.

    READ-ONLY CONTRACT: All implementations must be strictly read-only.
    No method may create, modify, delete, or mutate any cloud resource.
    This contract is enforced by tests that scan adapter subclasses for
    mutating method names. Violations fail CI.
    """

    @abstractmethod
    def list_resources(self, ignore_regions: list[str] | None = None) -> list[Resource]:
        """
        Return every resource across ALL regions, excluding ignore_regions.
        Empty or None means scan everything — new regions are included automatically.
        Implementation uses Resource Explorer (AWS), Asset Inventory (GCP),
        or Resource Graph (Azure). Never hardcode resource types.
        """
        ...

    @abstractmethod
    def get_metrics(
        self,
        resource_id: str,
        resource_type: str,
        days: int = 90,
    ) -> MetricSummary:
        """
        Fetch usage metrics relevant to this resource type over the last N days.
        The adapter decides which metrics matter per resource type.
        Default is 90 days — covers quarterly usage patterns. Override via
        METRICS_LOOKBACK_DAYS env var (see cloudwatch.DEFAULT_METRICS_DAYS).
        """
        ...

    @abstractmethod
    def get_cost(
        self,
        resource_ids: list[str],
        days: int = 30,
    ) -> dict[str, float]:
        """
        Return estimated monthly cost in USD per resource ID.
        Always batch resource_ids — never call per-resource.
        """
        ...

    @abstractmethod
    def get_last_activity(
        self,
        resource_id: str,
        resource_type: str,
    ) -> datetime | None:
        """
        Return the timestamp of the last meaningful activity for this resource.
        Returns None if no activity found in the lookback window.
        """
        ...
