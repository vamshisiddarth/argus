from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# BigQuery dataset where Cloud Billing export is written.
# Users must enable billing export to BigQuery — this is the standard GCP cost path.
# Set via BILLING_BQ_DATASET env var: "project.dataset" or "project.dataset.table"
_DEFAULT_TABLE = "argus_billing.gcp_billing_export_v1"


def get_cost(
    project_id: str,
    resource_ids: list[str],
    days: int = 30,
    bq_table: str | None = None,
) -> dict[str, float]:
    """
    Return estimated cost in USD per resource ID over the last N days.

    GCP billing data is available via two paths:
    1. Cloud Billing Budget API — account-level budgets only, no per-resource breakdown.
    2. BigQuery billing export — per-resource cost, requires export to be enabled.

    We use the BigQuery export path since it's the only way to get per-resource cost.
    If the export table doesn't exist or isn't configured, returns zeros with a warning.

    The caller is responsible for passing resource_ids as the full GCP resource names
    (//compute.googleapis.com/projects/…) — we extract the short name for BQ filtering.
    """
    if not resource_ids:
        return {}

    import os

    resolved_table = bq_table or os.environ.get("BILLING_BQ_TABLE", _DEFAULT_TABLE)

    try:
        return _query_bigquery(project_id, resource_ids, days, resolved_table or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "gcp_billing_query_failed",
            extra={
                "project_id": project_id,
                "error": str(exc),
                "hint": (
                    "Enable Cloud Billing export to BigQuery in the GCP console "
                    "(Billing → Billing export → BigQuery export). "
                    "Set BILLING_BQ_TABLE env var to 'project.dataset.table'."
                ),
            },
        )
        return {rid: 0.0 for rid in resource_ids}


def _query_bigquery(
    project_id: str,
    resource_ids: list[str],
    days: int,
    bq_table: str,
) -> dict[str, float]:
    from google.cloud import bigquery  # type: ignore[import-untyped,attr-defined]

    client = bigquery.Client(project=project_id)
    end_date = datetime.now(tz=timezone.utc).date()
    start_date = end_date - timedelta(days=days)

    # Extract short resource names from full asset names for matching.
    # Full: //compute.googleapis.com/projects/p/zones/z/instances/my-vm
    # Short: my-vm
    short_names = [rid.rstrip("/").split("/")[-1] for rid in resource_ids]
    name_to_full = {rid.rstrip("/").split("/")[-1]: rid for rid in resource_ids}

    placeholders = ", ".join(f"@name_{i}" for i in range(len(short_names)))
    query = f"""
        SELECT
            resource.name AS resource_name,
            SUM(cost) AS total_cost
        FROM `{bq_table}`
        WHERE
            DATE(usage_start_time) >= @start_date
            AND DATE(usage_end_time) <= @end_date
            AND resource.name IN ({placeholders})
        GROUP BY resource.name
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date.isoformat()),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date.isoformat()),
            *[
                bigquery.ScalarQueryParameter(f"name_{i}", "STRING", name)
                for i, name in enumerate(short_names)
            ],
        ]
    )

    costs: dict[str, float] = {rid: 0.0 for rid in resource_ids}
    results = client.query(query, job_config=job_config).result()

    for row in results:
        short = row.resource_name
        full_id = name_to_full.get(short)
        if full_id:
            costs[full_id] = round(float(row.total_cost), 4)

    logger.info(
        "gcp_billing_query_complete",
        extra={
            "project_id": project_id,
            "resources_queried": len(resource_ids),
            "resources_with_cost": sum(1 for v in costs.values() if v > 0),
        },
    )
    return costs
