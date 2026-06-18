"""
GCP Cloud Run Job entrypoint for Argus.

Cloud Run Jobs run to completion — no HTTP server needed. The job is
triggered on a schedule by Cloud Scheduler.

Environment variables:
  GCP_PROJECT_ID              GCP project to scan (required)
  BILLING_BQ_TABLE            BigQuery billing export table (optional)
                              e.g. my-project.billing_dataset.gcp_billing_export_v1
  IGNORE_REGIONS              Comma-separated regions to exclude (default: empty)
  AI_PROVIDER                 "anthropic" | "vertexai" (default: vertexai)
  ANTHROPIC_API_KEY           Required when AI_PROVIDER=anthropic
  VERTEXAI_PROJECT            GCP project for Vertex AI (defaults to GCP_PROJECT_ID)
  VERTEXAI_LOCATION           Vertex AI region (default: us-central1)
  SLACK_WEBHOOK_URL           Slack incoming webhook URL
  DRY_RUN                     "true" to skip Slack post (default: false)
  REPORT_GCS_BUCKET           GCS bucket name for full reports (JSON + HTML) (optional)
  REPORT_URL_EXPIRY           Signed URL expiry in seconds (default: 604800 = 7 days)
  LOG_LEVEL                   DEBUG | INFO | WARNING | ERROR (default: INFO)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from adapters.gcp.adapter import GCPAdapter
from core.agent.loop import AgentLoop
from core.reports.delivery import SlackDeliveryError, post_to_slack
from core.reports.generator import build_report, build_slack_payload
from core.reports.html import build_html_report

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Entry point for the Cloud Run Job. Runs once and exits."""
    cloud = "gcp"
    ignore_regions = [
        r.strip() for r in os.environ.get("IGNORE_REGIONS", "").split(",") if r.strip()
    ]

    project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project_id:
        logger.error("GCP_PROJECT_ID is not set — cannot scan")
        sys.exit(1)

    logger.info(
        "scan_start cloud=%s project=%s ignore_regions=%s",
        cloud,
        project_id,
        ignore_regions,
    )

    ai_provider = _build_ai_provider(project_id)
    adapter = GCPAdapter.from_env()

    loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
    findings, executive_summary = loop.run(
        cloud=cloud,
        ignore_regions=ignore_regions,
        accounts=[{"id": project_id, "name": project_id}],
    )

    report = build_report(
        findings,
        cloud=cloud,
        executive_summary=executive_summary,
        accounts_scanned=[project_id],
    )

    gcs_bucket = os.environ.get("REPORT_GCS_BUCKET", "").strip()
    report_url: str | None = None
    if gcs_bucket:
        report_url = _save_reports_to_gcs(report, gcs_bucket)

    payload = build_slack_payload(report, report_url=report_url)
    try:
        post_to_slack(payload)
    except (SlackDeliveryError, OSError) as exc:
        logger.error("slack_delivery_failed: %s", exc)

    logger.info(
        "scan_complete findings=%d total_waste_usd=%.2f scan_id=%s",
        report["findings_count"],
        report["total_estimated_waste_usd"],
        report["scan_id"],
    )


def _build_ai_provider(project_id: str) -> Any:
    provider_name = os.environ.get("AI_PROVIDER", "vertexai").lower()
    if provider_name == "anthropic":
        from ai.anthropic import AnthropicProvider

        return AnthropicProvider()
    from ai.vertexai import VertexAIProvider

    return VertexAIProvider(
        project=os.environ.get("VERTEXAI_PROJECT", project_id),
        location=os.environ.get("VERTEXAI_LOCATION", "us-central1"),
    )


def _save_reports_to_gcs(report: dict[str, Any], bucket_name: str) -> str | None:
    """Upload JSON + HTML reports to GCS. Returns a signed URL for the HTML report."""
    try:
        from google.api_core import (
            exceptions as google_exceptions,  # type: ignore[import-untyped]
        )
        from google.cloud import storage  # type: ignore[import-untyped,attr-defined]
    except ImportError:
        logger.error(
            "google-cloud-storage is not installed — skipping GCS upload. "
            "Run: pip install google-cloud-storage"
        )
        return None

    now = datetime.now(tz=timezone.utc)
    prefix = f"reports/{report['cloud']}/{now.strftime('%Y/%m/%d')}/{report['scan_id']}"
    json_key = f"{prefix}.json"
    html_key = f"{prefix}.html"
    expiry_seconds = int(os.environ.get("REPORT_URL_EXPIRY", "604800"))

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        json_blob = bucket.blob(json_key)
        json_blob.upload_from_string(
            json.dumps(report, indent=2, default=str).encode("utf-8"),
            content_type="application/json",
        )
        logger.info("json report saved to gs://%s/%s", bucket_name, json_key)

        html_blob = bucket.blob(html_key)
        html_blob.upload_from_string(
            build_html_report(report).encode("utf-8"),
            content_type="text/html; charset=utf-8",
        )
        logger.info("html report saved to gs://%s/%s", bucket_name, html_key)

        url: str = html_blob.generate_signed_url(
            expiration=timedelta(seconds=expiry_seconds),
            method="GET",
            version="v4",
        )
        logger.info("signed url generated (expires in %ds)", expiry_seconds)
        return url
    except google_exceptions.GoogleAPIError as exc:
        logger.error("failed to save reports to GCS: %s", exc)
        return None


if __name__ == "__main__":
    main()
