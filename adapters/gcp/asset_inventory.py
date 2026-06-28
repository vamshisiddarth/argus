from __future__ import annotations

from typing import Any

import structlog
from google.api_core.exceptions import (
    GoogleAPICallError,
    InvalidArgument,
    NotFound,
    PermissionDenied,
)
from google.cloud import asset_v1

from adapters.base import Resource
from adapters.gcp.retry import retry_on_transient

logger = structlog.get_logger(__name__)

# Asset types Argus cares about. Empty list = all types (too noisy for cost analysis).
# We scope to resource types that have associated billing.
SCANNED_ASSET_TYPES: list[str] = [
    # --- Compute ---
    "compute.googleapis.com/Instance",
    "compute.googleapis.com/Disk",
    "container.googleapis.com/Cluster",  # GKE
    "run.googleapis.com/Service",  # Cloud Run
    "cloudfunctions.googleapis.com/Function",
    "appengine.googleapis.com/Application",  # App Engine
    "composer.googleapis.com/Environment",  # Cloud Composer (Airflow)
    "notebooks.googleapis.com/Instance",  # Vertex AI Workbench
    "aiplatform.googleapis.com/Endpoint",  # Vertex AI endpoints
    # --- Networking ---
    "compute.googleapis.com/Address",  # static IPs
    "compute.googleapis.com/ForwardingRule",  # load balancers
    "compute.googleapis.com/BackendService",
    "compute.googleapis.com/Router",  # Cloud NAT
    "compute.googleapis.com/VpnTunnel",
    "vpcaccess.googleapis.com/Connector",  # Serverless VPC
    # --- Databases ---
    "sqladmin.googleapis.com/Instance",  # Cloud SQL
    "spanner.googleapis.com/Instance",
    "bigtable.googleapis.com/Instance",
    "alloydb.googleapis.com/Cluster",  # AlloyDB (managed Postgres)
    "firestore.googleapis.com/Database",
    "redis.googleapis.com/Instance",  # Memorystore Redis
    "memcache.googleapis.com/Instance",  # Memorystore Memcached
    "file.googleapis.com/Instance",  # Filestore (managed NFS)
    # --- Data & Messaging ---
    "storage.googleapis.com/Bucket",
    "bigquery.googleapis.com/Dataset",
    "bigquery.googleapis.com/Table",
    "pubsub.googleapis.com/Topic",
    "pubsub.googleapis.com/Subscription",
    "dataflow.googleapis.com/Job",
    "dataproc.googleapis.com/Cluster",
    "cloudtasks.googleapis.com/Queue",  # Cloud Tasks
]


def list_resources(
    project_id: str,
    ignore_regions: list[str] | None = None,
) -> tuple[list[Resource], list[str]]:
    """
    Return (resources, skipped_asset_types) for a GCP project.

    Uses a single paginated Cloud Asset Inventory call. If any asset type's API
    is not enabled in the project, INVALID_ARGUMENT is returned for that type.
    We strip it and retry so a project without Bigtable/Spanner/etc. enabled
    doesn't block the whole scan. Callers receive the list of skipped types so
    they can surface a warning in the Slack digest.
    """
    client = asset_v1.AssetServiceClient()
    parent = f"projects/{project_id}"
    ignore_set = set(ignore_regions or [])
    resources: list[Resource] = []
    asset_types = list(SCANNED_ASSET_TYPES)  # mutable — bad types get stripped
    skipped_types: list[str] = []

    while True:
        request = asset_v1.ListAssetsRequest(
            parent=parent,
            asset_types=asset_types,
            content_type=asset_v1.ContentType.RESOURCE,
        )
        try:
            for asset in retry_on_transient(
                client.list_assets, request=request, timeout=60
            ):
                parsed = _parse_asset(asset, ignore_set)
                if parsed:
                    resources.append(parsed)
            break  # success — exit retry loop
        except InvalidArgument as exc:
            # An asset type whose API is not enabled in this project causes
            # INVALID_ARGUMENT. Strip it and retry with the remaining types.
            bad_type = _extract_bad_asset_type(str(exc), asset_types)
            if bad_type:
                logger.warning(
                    "asset_type_api_not_enabled_skipping",
                    asset_type=bad_type,
                    project_id=project_id,
                )
                skipped_types.append(bad_type)
                asset_types.remove(bad_type)
                resources = []  # reset — avoid duplicates from partial page
            else:
                raise RuntimeError(
                    f"Cloud Asset Inventory INVALID_ARGUMENT (unknown type): {exc}"
                ) from exc
        except (PermissionDenied, NotFound) as exc:
            raise PermissionError(
                f"Project '{project_id}' not found or Argus lacks permission. "
                f"Check the project ID and ensure cloudasset.assets.listAssets "
                f"is granted to your credentials."
            ) from exc
        except GoogleAPICallError as exc:
            raise RuntimeError(f"Cloud Asset Inventory API error: {exc}") from exc

    logger.info(
        "asset_inventory_complete",
        extra={"project_id": project_id, "total": len(resources)},
    )
    return resources, skipped_types


def _extract_bad_asset_type(error_msg: str, asset_types: list[str]) -> str | None:
    """Return the first asset type string found in the INVALID_ARGUMENT error message."""
    for asset_type in asset_types:
        if asset_type in error_msg:
            return asset_type
    return None


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
