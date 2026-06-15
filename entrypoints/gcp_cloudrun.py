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
  LOG_LEVEL                   DEBUG | INFO | WARNING | ERROR (default: INFO)
"""

from __future__ import annotations

import logging
import os
import sys

from adapters.gcp.adapter import GCPAdapter
from core.agent.loop import AgentLoop
from core.reports.delivery import post_to_slack
from core.reports.generator import build_report, build_slack_payload

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

    payload = build_slack_payload(report)
    post_to_slack(payload)

    logger.info(
        "scan_complete findings=%d total_waste_usd=%.2f scan_id=%s",
        report["findings_count"],
        report["total_estimated_waste_usd"],
        report["scan_id"],
    )


def _build_ai_provider(project_id: str):
    provider_name = os.environ.get("AI_PROVIDER", "vertexai").lower()
    if provider_name == "anthropic":
        from ai.anthropic import AnthropicProvider

        return AnthropicProvider()
    from ai.vertexai import VertexAIProvider

    return VertexAIProvider(
        project=os.environ.get("VERTEXAI_PROJECT", project_id),
        location=os.environ.get("VERTEXAI_LOCATION", "us-central1"),
    )


if __name__ == "__main__":
    main()
