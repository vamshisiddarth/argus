"""Last event time of a CloudWatch Logs group.

CloudTrail does not record log ingestion, so asking it about a busy log group
returns nothing and looks like idleness. The newest stream's last event time is
the real signal. A failed lookup raises: it is missing evidence, never idleness.
"""

from __future__ import annotations

from datetime import datetime, timezone

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError

from adapters.aws.config import BOTO_TIMEOUT_CONFIG
from adapters.aws.retry import retry_on_transient
from adapters.base import ActivityUnavailableError

logger = structlog.get_logger(__name__)


def is_log_group(resource_type: str) -> bool:
    squashed = "".join(ch for ch in resource_type.lower() if ch.isalnum())
    return "loggroup" in squashed


def log_group_name(resource_id: str) -> str:
    """arn:aws:logs:region:acct:log-group:NAME[:*] -> NAME."""
    marker = "log-group:"
    name = resource_id.split(marker, 1)[1] if marker in resource_id else resource_id
    return name[:-2] if name.endswith(":*") else name


def get_last_event(session: boto3.Session, resource_id: str) -> datetime | None:
    """UTC time of the newest log event, or None if the group has no events."""
    parts = resource_id.split(":")
    region = (parts[3] if len(parts) > 3 else "") or "us-east-1"
    name = log_group_name(resource_id)
    client = session.client("logs", region_name=region, config=BOTO_TIMEOUT_CONFIG)
    try:
        resp = retry_on_transient(
            client.describe_log_streams,
            logGroupName=name,
            orderBy="LastEventTime",
            descending=True,
            limit=1,
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        logger.warning("log_activity_failed", resource_id=resource_id, error=code)
        raise ActivityUnavailableError(
            f"CloudWatch Logs lookup failed: {code}"
        ) from exc
    except BotoCoreError as exc:
        raise ActivityUnavailableError("CloudWatch Logs lookup failed") from exc
    streams = resp.get("logStreams", [])
    stamp = streams[0].get("lastEventTimestamp") if streams else None
    if stamp is None:
        return None
    return datetime.fromtimestamp(stamp / 1000, tz=timezone.utc)
