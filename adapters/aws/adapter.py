from __future__ import annotations

import os
from datetime import datetime

import boto3

from adapters.aws import auth, cloudtrail, cloudwatch, cost_explorer, resource_explorer
from adapters.aws.preflight import run_preflight
from adapters.aws.state import collect_state
from adapters.aws.tags import fetch_tags
from adapters.base import CloudAdapter, MetricSummary, Resource
from core.models.preflight import PreflightResult


class AWSAdapter(CloudAdapter):
    """
    AWS implementation of CloudAdapter.
    Wires together Resource Explorer, CloudWatch, Cost Explorer, and CloudTrail.
    All boto3 calls are read-only — no mutations to cloud resources.

    Usage:
        session = auth.get_session(account=account_config, region="us-east-1")
        adapter = AWSAdapter(session)
    """

    # GetCostAndUsageWithResources only holds the last 14 days
    max_cost_days: int | None = 14

    def __init__(
        self,
        session: boto3.Session,
        aggregator_region: str | None = None,
    ) -> None:
        self._session = session
        self.discovery_complete: bool | None = None
        self.filtered_by_type: dict[str, int] = {}
        # Where the tags came from: "resource_explorer", "tagging_api", "unavailable"
        self.tags_source: str | None = None
        self._aggregator_region: str = (
            aggregator_region
            or os.environ.get("RESOURCE_EXPLORER_REGION")
            or "us-east-1"
        )

    def preflight(self, account_id: str | None = None) -> PreflightResult:
        """Read-only environment checks to run before spending any LLM budget."""
        return run_preflight(self._session, self._aggregator_region, account_id)

    def list_resources(self, ignore_regions: list[str] | None = None) -> list[Resource]:
        found = resource_explorer.discover(
            session=self._session,
            ignore_regions=ignore_regions,
            aggregator_region=self._aggregator_region,
        )
        self.discovery_complete = found.complete
        self.filtered_by_type = found.filtered_by_type
        self._fill_missing_tags(found.resources)
        return found.resources

    def _fill_missing_tags(self, resources: list[Resource]) -> None:
        """If Resource Explorer gave no tags at all, ask the Tagging API."""
        if not resources:
            return
        if any(r.tags for r in resources):
            self.tags_source = "resource_explorer"
            return
        fetched = fetch_tags(self._session, resources, self._aggregator_region)
        if fetched is None:
            self.tags_source = "unavailable"
            return
        self.tags_source = "tagging_api"
        for r in resources:
            tags = fetched.get(r.resource_id)
            if tags:
                r.tags = tags
                r.name = r.name or tags.get("Name")

    def collect_state(self, resources: list[Resource]) -> dict[str, dict]:
        return collect_state(self._session, resources)

    def get_metrics(
        self,
        resource_id: str,
        resource_type: str,
        days: int = 90,
    ) -> MetricSummary:
        return cloudwatch.get_metrics(
            session=self._session,
            resource_id=resource_id,
            resource_type=resource_type,
            days=days,
        )

    def get_cost(
        self,
        resource_ids: list[str],
        days: int = 30,
    ) -> dict[str, float]:
        return cost_explorer.get_cost(
            session=self._session,
            resource_ids=resource_ids,
            days=days,
        )

    def get_last_activity(
        self,
        resource_id: str,
        resource_type: str,
    ) -> datetime | None:
        return cloudtrail.get_last_activity(
            session=self._session,
            resource_id=resource_id,
            resource_type=resource_type,
        )

    @classmethod
    def for_account(
        cls,
        account: dict | None = None,
        region: str = "us-east-1",
    ) -> "AWSAdapter":
        """Convenience constructor — resolves auth and returns a ready adapter."""
        session = auth.get_session(account=account, region=region)
        # Pass aggregator_region=None so __init__ honours RESOURCE_EXPLORER_REGION
        # env var before falling back to the default "us-east-1".
        return cls(session=session, aggregator_region=None)
