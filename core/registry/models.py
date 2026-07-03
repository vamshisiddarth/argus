from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricSpec:
    name: str
    namespace: str
    stat: str
    dimension_key: str


@dataclass(frozen=True)
class ResourceTypeSpec:
    type_id: str
    cloud: str
    display_name: str
    service: str
    metrics: tuple[MetricSpec, ...] = field(default_factory=tuple)
    typical_monthly_cost_usd: float | None = None
    docs_url: str | None = None
