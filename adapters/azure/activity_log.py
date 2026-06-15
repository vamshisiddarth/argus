from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus
from azure.core.exceptions import HttpResponseError

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90  # Azure Activity Log retention is 90 days


def get_last_activity(
    subscription_id: str,
    resource_id: str,
    resource_type: str,
    credential: Any = None,
) -> datetime | None:
    """
    Return the timestamp of the most recent activity for an Azure resource.
    Queries Azure Monitor Activity Log via the Logs Query (Log Analytics) API.

    Falls back to None if:
    - Log Analytics workspace is not configured
    - No activity found in the 90-day window
    - API call fails

    resource_id is the full Azure resource ID:
    /subscriptions/{sub}/resourceGroups/{rg}/providers/{type}/{name}
    """
    cred = credential or DefaultAzureCredential()
    client = LogsQueryClient(cred)

    # Log Analytics workspace for the subscription — set via env var.
    import os

    workspace_id = os.environ.get("AZURE_LOG_ANALYTICS_WORKSPACE_ID", "")

    if not workspace_id:
        logger.debug(
            "azure_activity_log_skipped",
            extra={
                "resource_id": resource_id,
                "reason": "AZURE_LOG_ANALYTICS_WORKSPACE_ID not set",
            },
        )
        return _fallback_from_activity_log_api(subscription_id, resource_id, credential)

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=_LOOKBACK_DAYS)

    # KQL query — finds the most recent write/action operation on this resource
    query = f"""
    AzureActivity
    | where ResourceId =~ "{resource_id}"
    | where OperationNameValue !endswith "/read"
    | order by TimeGenerated desc
    | take 1
    | project TimeGenerated
    """

    try:
        response = client.query_workspace(
            workspace_id=workspace_id,
            query=query,
            timespan=(start_time, end_time),
        )
    except HttpResponseError as exc:
        logger.warning(
            "azure_log_analytics_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )
        return None

    if response.status != LogsQueryStatus.SUCCESS:
        return None

    for table in response.tables:
        for row in table.rows:
            event_time = row[0]
            if isinstance(event_time, str):
                from dateutil.parser import parse

                event_time = parse(event_time)
            if event_time and event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            return event_time

    return None


def _fallback_from_activity_log_api(
    subscription_id: str,
    resource_id: str,
    credential: Any,
) -> datetime | None:
    """
    Direct Activity Log API fallback when Log Analytics workspace isn't configured.
    Uses azure-mgmt-monitor to query the activity log REST endpoint directly.
    Only available if azure-mgmt-monitor is installed.
    """
    try:
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore[import-untyped]
    except ImportError:
        return None

    cred = credential or DefaultAzureCredential()
    client = MonitorManagementClient(cred, subscription_id)

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=_LOOKBACK_DAYS)

    filter_str = (
        f"eventTimestamp ge '{start_time.isoformat()}' "
        f"and eventTimestamp le '{end_time.isoformat()}' "
        f"and resourceUri eq '{resource_id}'"
    )

    try:
        events = list(
            client.activity_logs.list(
                filter=filter_str,
                select="eventTimestamp,operationName",
            )
        )
    except HttpResponseError as exc:
        logger.warning(
            "azure_activity_log_api_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )
        return None

    # Filter out read-only operations
    write_events = [
        e
        for e in events
        if e.operation_name
        and not str(e.operation_name.value or "").lower().endswith("/read")
    ]

    if not write_events:
        return None

    # Events come back newest-first
    event_time: datetime = write_events[0].event_timestamp
    if event_time and event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    return event_time
