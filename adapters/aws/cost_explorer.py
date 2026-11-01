from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3
import structlog
from botocore.exceptions import ClientError

from adapters.aws.config import BOTO_TIMEOUT_CONFIG
from adapters.aws.retry import retry_on_transient

logger = structlog.get_logger(__name__)

# Cost Explorer is a global service - always us-east-1
_CE_REGION = "us-east-1"

# Resource-level data only exists for the last 14 days
_RESOURCE_LEVEL_MAX_DAYS = 14

_warned: set[str] = set()

_HINTS = {
    "cost_explorer_resource_level_not_enabled": (
        "Resource-level cost data is not enabled. Enable it in the PAYER "
        "(management) account: Cost Management > Cost Explorer settings > "
        "Resource-level data. Until then per-resource costs are unavailable."
    ),
    "cost_explorer_not_activated": (
        "Cost Explorer has not been enabled for this AWS account. Activate it in "
        "the AWS Cost Management console (takes up to 24 hours)."
    ),
    "cost_explorer_access_denied": (
        "IAM principal is missing ce:GetCostAndUsageWithResources permission. "
        "Add it to the Argus IAM role."
    ),
}


def _classify(exc: ClientError) -> tuple[str, str]:
    """Map a Cost Explorer error to (log event name, hint)."""
    code = exc.response["Error"]["Code"]
    text = exc.response["Error"].get("Message", "").lower()
    if (
        code == "DataUnavailableException"
        or "opt-in" in text
        or "resource-level" in text
        or "granularity" in text
    ):
        kind = "cost_explorer_resource_level_not_enabled"
    elif code == "AccessDeniedException" and "not enabled for cost explorer" in text:
        kind = "cost_explorer_not_activated"
    elif code == "AccessDeniedException":
        kind = "cost_explorer_access_denied"
    else:
        return "cost_explorer_failed", f"Cost Explorer call failed ({code})."
    return kind, _HINTS[kind]


def _warn_once(kind: str, **fields: str) -> None:
    """Log each distinct Cost Explorer failure once per process."""
    if kind in _warned:
        return
    _warned.add(kind)
    log = logger.error if kind == "cost_explorer_failed" else logger.warning
    log(kind, **fields)


def probe_resource_level_cost(session: boto3.Session) -> str | None:
    """Cheap check (one $0.01 call): None if per-resource cost works, else a reason."""
    client = session.client("ce", region_name=_CE_REGION, config=BOTO_TIMEOUT_CONFIG)
    end = datetime.now(tz=timezone.utc).date()
    start = end - timedelta(days=2)
    try:
        client.get_cost_and_usage_with_resources(
            TimePeriod={
                "Start": start.strftime("%Y-%m-%d"),
                "End": end.strftime("%Y-%m-%d"),
            },
            Granularity="DAILY",
            Filter={
                "Dimensions": {"Key": "RESOURCE_ID", "Values": ["argus-preflight"]}
            },
            Metrics=["UnblendedCost"],
        )
    except ClientError as exc:
        return _classify(exc)[1]
    except Exception as exc:  # noqa: BLE001
        return f"Cost Explorer check failed ({type(exc).__name__})."
    return None


def get_cost(
    session: boto3.Session,
    resource_ids: list[str],
    days: int = 30,
) -> dict[str, float]:
    """
    Return estimated monthly cost in USD per resource ID.

    Uses GetCostAndUsageWithResources which requires resource-level cost
    allocation to be enabled in the AWS Cost Management console.
    If not enabled, returns zeros and logs a warning — the agent will
    note that cost data is unavailable for these resources.

    The request window is clamped to 14 days, the most that resource-level data holds.

    IMPORTANT: Always batch resource_ids — this is one API call regardless
    of how many IDs are passed. Cost Explorer charges $0.01 per API call.
    """
    if not resource_ids:
        return {}

    client = session.client("ce", region_name=_CE_REGION, config=BOTO_TIMEOUT_CONFIG)

    end_date = datetime.now(tz=timezone.utc).date()
    start_date = end_date - timedelta(days=min(days, _RESOURCE_LEVEL_MAX_DAYS))

    try:
        response = retry_on_transient(
            client.get_cost_and_usage_with_resources,
            TimePeriod={
                "Start": start_date.strftime("%Y-%m-%d"),
                "End": end_date.strftime("%Y-%m-%d"),
            },
            Granularity="MONTHLY",
            Filter={
                "Dimensions": {
                    "Key": "RESOURCE_ID",
                    "Values": resource_ids,
                }
            },
            GroupBy=[{"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
            Metrics=["UnblendedCost"],
        )
    except ClientError as exc:
        kind, hint = _classify(exc)
        _warn_once(kind, hint=hint, error=str(exc))
        return {rid: 0.0 for rid in resource_ids}

    costs: dict[str, float] = {rid: 0.0 for rid in resource_ids}

    for time_period in response.get("ResultsByTime", []):
        for group in time_period.get("Groups", []):
            resource_id = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            # Accumulate across months if days > 31
            costs[resource_id] = costs.get(resource_id, 0.0) + amount

    logger.info(
        "cost_explorer_complete",
        resources_queried=len(resource_ids),
        resources_with_cost=sum(1 for v in costs.values() if v > 0),
    )
    return costs
