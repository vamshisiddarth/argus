from __future__ import annotations

from typing import Any

import structlog
from google.api_core.exceptions import GoogleAPICallError, PermissionDenied
from google.cloud import asset_v1

from adapters.base import Resource
from adapters.gcp.retry import retry_on_transient

logger = structlog.get_logger(__name__)

# Asset types Argus cares about. Empty list = all types (too noisy for cost analysis).
# We scope to resource types that have associated billing.
SCANNED_ASSET_TYPES: list[str] = [
    "compute.googleapis.com/Instance",
    "compute.googleapis.com/Disk",
    "compute.googleapis.com/Address",  # static IPs
    "compute.googleapis.com/ForwardingRule",
    "compute.googleapis.com/BackendService",
    "sql.googleapis.com/Instance",  # Cloud SQL
    "container.googleapis.com/Cluster",  # GKE
    "run.googleapis.com/Service",  # Cloud Run
    "cloudfunctions.googleapis.com/Function",  # Cloud Functions
    "storage.googleapis.com/Bucket",
    "bigquery.googleapis.com/Dataset",
    "bigquery.googleapis.com/Table",
    "redis.googleapis.com/Instance",  # Memorystore Redis
    "spanner.googleapis.com/Instance",
    "bigtable.googleapis.com/Instance",
    "pubsub.googleapis.com/Topic",
    "pubsub.googleapis.com/Subscription",
    "dataflow.googleapis.com/Job",
    "dataproc.googleapis.com/Cluster",
    "aiplatform.googleapis.com/Endpoint",  # Vertex AI
    "composer.googleapis.com/Environment",  # Cloud Composer (Airflow)
    "notebooks.googleapis.com/Instance",  # Vertex AI Workbench
]


def list_resources(
    project_id: str,
    ignore_regions: list[str] | None = None,
) -> list[Resource]:
    """
    Return all billable GCP resources in a project using Cloud Asset Inventory.
    Uses a single paginated API call — no per-resource-type enumeration needed.
    """
    client = asset_v1.AssetServiceClient()
    parent = f"projects/{project_id}"
    ignore_set = set(ignore_regions or [])
    resources: list[Resource] = []

    request = asset_v1.ListAssetsRequest(
        parent=parent,
        asset_types=SCANNED_ASSET_TYPES,
        content_type=asset_v1.ContentType.RESOURCE,
    )

    try:
        for asset in retry_on_transient(
            client.list_assets, request=request, timeout=60
        ):
            parsed = _parse_asset(asset, ignore_set)
            if parsed:
                resources.append(parsed)
    except PermissionDenied as exc:
        raise PermissionError(
            f"Argus service account is missing cloudasset.assets.listAssets "
            f"permission on project {project_id}."
        ) from exc
    except GoogleAPICallError as exc:
        raise RuntimeError(f"Cloud Asset Inventory API error: {exc}") from exc

    logger.info(
        "asset_inventory_complete",
        extra={"project_id": project_id, "total": len(resources)},
    )
    return resources


def _parse_asset(asset: Any, ignore_set: set[str]) -> Resource | None:
    resource = asset.resource
    if not resource:
        return None

    data: dict[str, Any] = dict(resource.data)
    name: str = asset.name  # full resource name: //compute.googleapis.com/projects/…
    asset_type: str = asset.asset_type  # e.g. compute.googleapis.com/Instance
    location: str = data.get("location", data.get("zone", data.get("region", "global")))

    # Normalise zone (us-central1-a) to region (us-central1)
    region = _to_region(location)
    if region in ignore_set:
        return None

    labels: dict[str, str] = dict(data.get("labels", {}))
    friendly_name: str | None = data.get("name") or data.get("displayName")

    return Resource(
        resource_id=name,
        resource_type=asset_type,
        cloud="gcp",
        region=region,
        name=friendly_name,
        tags=labels,
    )


def _to_region(location: str) -> str:
    """Strip the zone suffix from a zone string to get the region."""
    parts = location.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
        return parts[0]
    return location
