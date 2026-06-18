from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90  # CloudTrail LookupEvents max window is 90 days


def get_last_activity(
    session: boto3.Session,
    resource_id: str,
    resource_type: str,
) -> datetime | None:
    """
    Return the timestamp of the most recent CloudTrail event for a resource.
    Returns None if no activity was found in the last 90 days.

    Uses the resource name (extracted from ARN) as the lookup attribute
    since CloudTrail indexes by resource name, not full ARN.
    """
    region = _region_from_arn(resource_id)
    resource_name = _resource_name_from_arn(resource_id)
    client = session.client("cloudtrail", region_name=region)

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=_LOOKBACK_DAYS)

    try:
        response = client.lookup_events(
            LookupAttributes=[
                {"AttributeKey": "ResourceName", "AttributeValue": resource_name}
            ],
            StartTime=start_time,
            EndTime=end_time,
            MaxResults=1,
        )
    except ClientError as exc:
        logger.warning(
            "cloudtrail_lookup_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )
        return None

    events = response.get("Events", [])
    if not events:
        return None

    event_time = events[0]["EventTime"]
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    return event_time  # type: ignore[no-any-return]


def _region_from_arn(arn: str) -> str:
    parts = arn.split(":")
    region = parts[3] if len(parts) > 3 else ""
    return region or "us-east-1"


def _resource_name_from_arn(arn: str) -> str:
    """
    Extract the short resource name from an ARN for CloudTrail lookup.
    CloudTrail indexes by resource name (e.g. 'i-0abc123'), not full ARN.
    """
    parts = arn.split(":")
    resource_part = ":".join(parts[5:])

    if "/" in resource_part:
        return resource_part.split("/")[-1]
    if ":" in resource_part:
        return resource_part.split(":")[-1]
    return resource_part
