from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryDefinition,
    QueryTimePeriod,
    QueryDataset,
    QueryGrouping,
    QueryFilter,
    QueryComparisonExpression,
)
from azure.core.exceptions import HttpResponseError

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50  # Cost Management API supports up to ~100 resource IDs per filter


def get_cost(
    subscription_id: str,
    resource_ids: list[str],
    days: int = 30,
    credential: Any = None,
) -> dict[str, float]:
    """
    Return estimated cost in USD per resource ID over the last N days.

    Uses Azure Cost Management QueryUsage API, batched to avoid filter size limits.
    Cost Management requires the subscription to have a spending plan (not free tier).
    Returns zeros with a warning if cost data is unavailable.
    """
    if not resource_ids:
        return {}

    cred = credential or DefaultAzureCredential()
    client = CostManagementClient(cred)
    scope = f"/subscriptions/{subscription_id}"

    costs: dict[str, float] = {rid: 0.0 for rid in resource_ids}

    # Process in batches to stay within API filter limits
    for i in range(0, len(resource_ids), _BATCH_SIZE):
        batch = resource_ids[i : i + _BATCH_SIZE]
        try:
            _query_batch(client, scope, batch, days, costs)
        except HttpResponseError as exc:
            if exc.status_code in (403, 404):
                logger.warning(
                    "azure_cost_management_unavailable",
                    extra={
                        "subscription_id": subscription_id,
                        "error": str(exc),
                        "hint": (
                            "Cost Management requires a paid Azure subscription. "
                            "Free trial accounts return no cost data."
                        ),
                    },
                )
                break
            logger.error(
                "azure_cost_management_failed",
                extra={"subscription_id": subscription_id, "error": str(exc)},
            )

    logger.info(
        "azure_cost_query_complete",
        extra={
            "subscription_id": subscription_id,
            "resources_queried": len(resource_ids),
            "resources_with_cost": sum(1 for v in costs.values() if v > 0),
        },
    )
    return costs


def _query_batch(
    client: CostManagementClient,
    scope: str,
    resource_ids: list[str],
    days: int,
    costs: dict[str, float],
) -> None:
    end_date = datetime.now(tz=timezone.utc)
    start_date = end_date - timedelta(days=days)

    query = QueryDefinition(
        type="Usage",
        timeframe="Custom",
        time_period=QueryTimePeriod(
            from_property=start_date,
            to=end_date,
        ),
        dataset=QueryDataset(
            granularity="None",
            aggregation={"totalCost": {"name": "PreTaxCost", "function": "Sum"}},  # type: ignore[dict-item]
            grouping=[QueryGrouping(type="Dimension", name="ResourceId")],
            filter=QueryFilter(
                dimensions=QueryComparisonExpression(
                    name="ResourceId",
                    operator="In",
                    values=resource_ids,
                )
            ),
        ),
    )

    result = client.query.usage(scope=scope, parameters=query)

    # Result rows: [cost, currency, resourceId]
    for row in result.rows if result and result.rows else []:
        if len(row) >= 3:
            amount = float(row[0])
            resource_id: str = str(row[2])
            # Match case-insensitively — Azure resource IDs are case-insensitive
            for rid in costs:
                if rid.lower() == resource_id.lower():
                    costs[rid] = costs[rid] + amount
                    break
