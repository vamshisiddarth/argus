from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from adapters.azure import activity_log, cost_management, monitor, resource_graph
from adapters.base import CloudAdapter, MetricSummary, Resource


class AzureAdapter(CloudAdapter):
    """
    Azure implementation of CloudAdapter.
    Wires together Resource Graph, Azure Monitor, Cost Management, and Activity Log.
    All API calls are read-only.

    Auth: DefaultAzureCredential — Managed Identity in production,
    az login / env vars for local dev.

    Usage:
        adapter = AzureAdapter(subscription_ids=["sub-id-1", "sub-id-2"])
    """

    def __init__(
        self,
        subscription_ids: list[str] | None = None,
        credential: Any = None,
    ) -> None:
        resolved = subscription_ids or _parse_subscription_ids()
        if not resolved:
            raise EnvironmentError(
                "No Azure subscription IDs configured. "
                "Pass subscription_ids= or set AZURE_SUBSCRIPTION_IDS "
                "(comma-separated)."
            )
        self._subscription_ids = resolved
        self._credential = credential

    def list_resources(self, ignore_regions: list[str] | None = None) -> list[Resource]:
        return resource_graph.list_resources(
            subscription_ids=self._subscription_ids,
            ignore_regions=ignore_regions,
            credential=self._credential,
        )

    def get_metrics(
        self,
        resource_id: str,
        resource_type: str,
        days: int = 90,
    ) -> MetricSummary:
        return monitor.get_metrics(
            resource_id=resource_id,
            resource_type=resource_type,
            days=days,
            credential=self._credential,
        )

    def get_cost(
        self,
        resource_ids: list[str],
        days: int = 30,
    ) -> dict[str, float]:
        # Cost Management is scoped per subscription — group by subscription
        # extracted from the resource ID and fan out.
        by_sub: dict[str, list[str]] = {}
        for rid in resource_ids:
            sub = _subscription_from_resource_id(rid)
            by_sub.setdefault(sub, []).append(rid)

        costs: dict[str, float] = {}
        for sub_id, rids in by_sub.items():
            costs.update(
                cost_management.get_cost(
                    subscription_id=sub_id,
                    resource_ids=rids,
                    days=days,
                    credential=self._credential,
                )
            )
        return costs

    def get_last_activity(
        self,
        resource_id: str,
        resource_type: str,
    ) -> datetime | None:
        sub = _subscription_from_resource_id(resource_id)
        return activity_log.get_last_activity(
            subscription_id=sub,
            resource_id=resource_id,
            resource_type=resource_type,
            credential=self._credential,
        )

    @classmethod
    def from_env(cls) -> "AzureAdapter":
        """Convenience constructor — reads all config from env vars."""
        return cls(subscription_ids=_parse_subscription_ids())


def _parse_subscription_ids() -> list[str]:
    raw = os.environ.get("AZURE_SUBSCRIPTION_IDS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _subscription_from_resource_id(resource_id: str) -> str:
    """
    Extract subscription ID from an Azure resource ID.
    Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/...
    """
    parts = resource_id.lower().split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""
