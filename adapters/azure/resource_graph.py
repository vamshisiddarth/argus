from __future__ import annotations

import logging
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from adapters.base import Resource

logger = logging.getLogger(__name__)

# KQL query — returns all resources with their type, location, tags, and resource group.
# We exclude resource types that have no billing impact (e.g. locks, role assignments).
_RESOURCE_QUERY = """
Resources
| where type !in~ (
    'microsoft.authorization/roleassignments',
    'microsoft.authorization/roledefinitions',
    'microsoft.authorization/locks',
    'microsoft.resources/deployments',
    'microsoft.resources/tags'
)
| project id, name, type, location, resourceGroup, tags, subscriptionId
"""

_PAGE_SIZE = 1000  # Resource Graph max per page


def list_resources(
    subscription_ids: list[str],
    ignore_regions: list[str] | None = None,
    credential: Any = None,
) -> list[Resource]:
    """
    Return all billable Azure resources across the given subscriptions
    using Azure Resource Graph (single cross-subscription query).

    Auth: DefaultAzureCredential — Managed Identity in production,
    az login / env vars for local dev.
    """
    cred = credential or DefaultAzureCredential()
    client = ResourceGraphClient(cred)
    ignore_set = {r.lower() for r in (ignore_regions or [])}
    resources: list[Resource] = []

    request = QueryRequest(
        subscriptions=subscription_ids,
        query=_RESOURCE_QUERY,
        options=QueryRequestOptions(result_format="objectArray", top=_PAGE_SIZE),
    )

    skip_token: str | None = None

    try:
        while True:
            if skip_token:
                request.options.skip_token = skip_token

            response = client.resources(request)

            for raw in response.data or []:
                parsed = _parse_resource(raw, ignore_set)
                if parsed:
                    resources.append(parsed)

            _raw_token = getattr(response, "skip_token", None) or getattr(
                response, "$skipToken", None
            )
            skip_token = _raw_token if isinstance(_raw_token, str) else None
            if not skip_token:
                break

    except HttpResponseError as exc:
        if exc.status_code == 403:
            raise PermissionError(
                "Argus service principal is missing Reader role "
                "on the subscription(s). "
                "Assign 'Reader' at the subscription scope."
            ) from exc
        raise

    logger.info(
        "resource_graph_query_complete",
        extra={"subscriptions": subscription_ids, "total": len(resources)},
    )
    return resources


def _parse_resource(raw: dict[str, Any], ignore_set: set[str]) -> Resource | None:
    resource_id: str = raw.get("id", "")
    name: str = raw.get("name", "")
    resource_type: str = raw.get("type", "")
    location: str = raw.get("location", "global")

    if not resource_id or not resource_type:
        return None
    if location.lower() in ignore_set:
        return None

    tags: dict[str, str] = {str(k): str(v) for k, v in (raw.get("tags") or {}).items()}

    return Resource(
        resource_id=resource_id,
        resource_type=resource_type.lower(),
        cloud="azure",
        region=location,
        name=name or None,
        tags=tags,
    )
