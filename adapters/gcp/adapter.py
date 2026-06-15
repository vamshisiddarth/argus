from __future__ import annotations

import os
from datetime import datetime

from adapters.base import CloudAdapter, MetricSummary, Resource
from adapters.gcp import asset_inventory, billing, cloud_logging, cloud_monitoring


class GCPAdapter(CloudAdapter):
    """
    GCP implementation of CloudAdapter.
    Wires together Cloud Asset Inventory, Cloud Monitoring, Billing (BigQuery),
    and Cloud Audit Logs. All API calls are read-only.

    Auth: uses Application Default Credentials (ADC).
    - Cloud Run Job: the service account attached to the job
    - Local dev: `gcloud auth application-default login`

    Usage:
        adapter = GCPAdapter(project_id="my-gcp-project")
    """

    def __init__(
        self,
        project_id: str | None = None,
        bq_billing_table: str | None = None,
    ) -> None:
        self._project_id = project_id or os.environ.get("GCP_PROJECT_ID", "")
        if not self._project_id:
            raise EnvironmentError(
                "GCP_PROJECT_ID is not set. "
                "Pass project_id= or export GCP_PROJECT_ID."
            )
        self._bq_billing_table = bq_billing_table or os.environ.get("BILLING_BQ_TABLE")

    def list_resources(self, ignore_regions: list[str] | None = None) -> list[Resource]:
        return asset_inventory.list_resources(
            project_id=self._project_id,
            ignore_regions=ignore_regions,
        )

    def get_metrics(
        self,
        resource_id: str,
        resource_type: str,
        days: int = 90,
    ) -> MetricSummary:
        return cloud_monitoring.get_metrics(
            project_id=self._project_id,
            resource_id=resource_id,
            resource_type=resource_type,
            days=days,
        )

    def get_cost(
        self,
        resource_ids: list[str],
        days: int = 30,
    ) -> dict[str, float]:
        return billing.get_cost(
            project_id=self._project_id,
            resource_ids=resource_ids,
            days=days,
            bq_table=self._bq_billing_table,
        )

    def get_last_activity(
        self,
        resource_id: str,
        resource_type: str,
    ) -> datetime | None:
        return cloud_logging.get_last_activity(
            project_id=self._project_id,
            resource_id=resource_id,
            resource_type=resource_type,
        )

    @classmethod
    def from_env(cls) -> "GCPAdapter":
        """Convenience constructor — reads all config from env vars."""
        return cls(
            project_id=os.environ.get("GCP_PROJECT_ID"),
            bq_billing_table=os.environ.get("BILLING_BQ_TABLE"),
        )
