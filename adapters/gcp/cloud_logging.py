from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import logging as gcp_logging

from adapters.gcp.retry import retry_on_transient

logger = structlog.get_logger(__name__)

_LOOKBACK_DAYS = 90  # Cloud Logging retention default is 30-400 days depending on tier


def get_last_activity(
    project_id: str,
    resource_id: str,
    resource_type: str,
) -> datetime | None:
    """
    Return the timestamp of the most recent admin/data activity for a GCP resource.
    Uses Cloud Audit Logs (Admin Activity + Data Access) via the Cloud Logging API.
    Returns None if no activity found in the last 90 days.

    resource_id is a full GCP asset name:
    //compute.googleapis.com/projects/p/zones/z/instances/my-vm
    """
    short_name = resource_id.rstrip("/").split("/")[-1]
    service = _service_from_resource_type(resource_type)

    client = gcp_logging.Client(project=project_id)

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=_LOOKBACK_DAYS)

    # Cloud Audit Log filter — matches admin activity on the specific resource.
    log_filter = (
        f'logName=("projects/{project_id}/logs/cloudaudit.googleapis.com%2Factivity" '
        f'OR "projects/{project_id}/logs/cloudaudit.googleapis.com%2Fdata_access") '
        f'AND resource.labels.resource_name:"{short_name}" '
        f'AND timestamp >= "{start_time.isoformat()}" '
        f'AND timestamp <= "{end_time.isoformat()}"'
    )
    if service:
        log_filter += f' AND protoPayload.serviceName="{service}"'

    try:
        entries = list(
            retry_on_transient(
                client.list_entries,
                filter_=log_filter,
                order_by=gcp_logging.DESCENDING,
                page_size=1,
                timeout=60,
            )
        )
    except GoogleAPICallError as exc:
        logger.warning(
            "cloud_logging_lookup_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )
        return None

    if not entries:
        return None

    event_time: datetime = entries[0].timestamp
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    return event_time


def _service_from_resource_type(resource_type: str) -> str | None:
    """Map GCP asset type to the Cloud Audit Log service name for tighter filtering."""
    mapping: dict[str, str] = {
        "compute.googleapis.com/Instance": "compute.googleapis.com",
        "compute.googleapis.com/Disk": "compute.googleapis.com",
        "sqladmin.googleapis.com/Instance": "cloudsql.googleapis.com",
        "container.googleapis.com/Cluster": "container.googleapis.com",
        "storage.googleapis.com/Bucket": "storage.googleapis.com",
        "bigquery.googleapis.com/Dataset": "bigquery.googleapis.com",
        "bigquery.googleapis.com/Table": "bigquery.googleapis.com",
        "run.googleapis.com/Service": "run.googleapis.com",
        "cloudfunctions.googleapis.com/Function": "cloudfunctions.googleapis.com",
        "pubsub.googleapis.com/Topic": "pubsub.googleapis.com",
        "redis.googleapis.com/Instance": "redis.googleapis.com",
        "spanner.googleapis.com/Instance": "spanner.googleapis.com",
        "dataflow.googleapis.com/Job": "dataflow.googleapis.com",
        "dataproc.googleapis.com/Cluster": "dataproc.googleapis.com",
        "aiplatform.googleapis.com/Endpoint": "aiplatform.googleapis.com",
    }
    return mapping.get(resource_type)
