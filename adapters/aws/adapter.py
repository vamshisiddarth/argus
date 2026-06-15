from __future__ import annotations

import os
from datetime import datetime

import boto3

from adapters.aws import auth, cloudtrail, cloudwatch, cost_explorer, resource_explorer
from adapters.base import CloudAdapter, MetricSummary, Resource


class AWSAdapter(CloudAdapter):
    """
    AWS implementation of CloudAdapter.
    Wires together Resource Explorer, CloudWatch, Cost Explorer, and CloudTrail.
    All boto3 calls are read-only — no mutations to cloud resources.

    Usage:
        session = auth.get_session(account=account_config, region="us-east-1")
        adapter = AWSAdapter(session)
    """

    def __init__(
        self,
        session: boto3.Session,
        aggregator_region: str | None = None,
    ) -> None:
        self._session = session
        self._aggregator_region: str = (
            aggregator_region
            or os.environ.get("RESOURCE_EXPLORER_REGION")
            or "us-east-1"
        )

    def list_resources(self, ignore_regions: list[str] | None = None) -> list[Resource]:
        return resource_explorer.list_resources(
            session=self._session,
            ignore_regions=ignore_regions,
            aggregator_region=self._aggregator_region,
        )

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
        return cls(session=session, aggregator_region=region)
