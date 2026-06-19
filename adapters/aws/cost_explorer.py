from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3
import structlog
from botocore.exceptions import ClientError

from adapters.aws.config import BOTO_TIMEOUT_CONFIG
from adapters.aws.retry import retry_on_transient

logger = structlog.get_logger(__name__)

# Cost Explorer is a global service — always us-east-1
_CE_REGION = "us-east-1"


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

    IMPORTANT: Always batch resource_ids — this is one API call regardless
    of how many IDs are passed. Cost Explorer charges $0.01 per API call.
    """
    if not resource_ids:
        return {}

    client = session.client("ce", region_name=_CE_REGION, config=BOTO_TIMEOUT_CONFIG)

    end_date = datetime.now(tz=timezone.utc).date()
    start_date = end_date - timedelta(days=days)

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
        code = exc.response["Error"]["Code"]
        message = exc.response["Error"].get("Message", "")

        if code == "DataUnavailableException":
            logger.warning(
                "cost_explorer_resource_granularity_disabled",
                hint=(
                    "Enable resource-level data in AWS Cost Management console "
                    "(Preferences → Resource-level data)."
                ),
            )
            return {rid: 0.0 for rid in resource_ids}

        if (
            code == "AccessDeniedException"
            and "not enabled for cost explorer" in message.lower()
        ):
            logger.warning(
                "cost_explorer_not_activated",
                hint=(
                    "Cost Explorer has not been enabled for this AWS account. "
                    "Activate it in the AWS Cost Management console "
                    "(takes up to 24 hours after first activation)."
                ),
            )
            return {rid: 0.0 for rid in resource_ids}

        if code == "AccessDeniedException":
            logger.warning(
                "cost_explorer_access_denied",
                hint=(
                    "IAM principal is missing "
                    "ce:GetCostAndUsageWithResources permission. "
                    "Add it to the Argus IAM role."
                ),
                error=str(exc),
            )
            return {rid: 0.0 for rid in resource_ids}

        logger.error("cost_explorer_failed", error=str(exc), code=code)
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
