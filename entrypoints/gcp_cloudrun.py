"""
GCP Cloud Run Job entrypoint for Argus.

Cloud Run Jobs run to completion — no HTTP server needed. The job is
triggered on a schedule by Cloud Scheduler.

Environment variables:
  GCP_PROJECT_ID              GCP project to scan (single-project mode)
  GCP_PROJECT_IDS             Comma-separated GCP projects (multi-project mode)
  ACCOUNTS_MODE               "single" | "multi" (default: single)
  ACCOUNTS_CONFIG             JSON array of project dicts when ACCOUNTS_MODE=multi
                              e.g. [{"id":"proj-1","name":"production"}]
  BILLING_BQ_TABLE            BigQuery billing export table (optional)
                              e.g. my-project.billing_dataset.gcp_billing_export_v1
  IGNORE_REGIONS              Comma-separated regions to exclude (default: empty)
  AI_PROVIDER                 "anthropic" | "vertexai" (default: vertexai)
  ANTHROPIC_API_KEY           Required when AI_PROVIDER=anthropic
  VERTEXAI_PROJECT            GCP project for Vertex AI (defaults to first project)
  VERTEXAI_LOCATION           Vertex AI region (default: us-central1)
  SLACK_WEBHOOK_URL           Slack incoming webhook URL
  DRY_RUN                     "true" to skip Slack post (default: false)
  REPORT_GCS_BUCKET           GCS bucket name for full reports (JSON + HTML) (optional)
  REPORT_URL_EXPIRY           Signed URL expiry in seconds (default: 604800 = 7 days)
  LOG_LEVEL                   DEBUG | INFO | WARNING | ERROR (default: INFO)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from adapters.gcp.adapter import GCPAdapter
from core.agent.loop import AgentLoop
from core.log import configure_logging
from core.models.finding import ResourceFinding
from core.registry import get_registry
from core.reports.comparison import compare_scans
from core.reports.delivery import (
    notify_all,
    save_reports_locally,
)
from core.reports.generator import (
    build_report,
    build_slack_payload,
    synthesize_executive_summary,
)
from core.reports.html import build_html_report
from core.secrets import resolve_secrets
from core.validation import ConfigurationError, validate_environment

configure_logging()
logger = structlog.get_logger(__name__)


def main() -> None:
    """Entry point for the Cloud Run Job. Runs once and exits."""
    cloud = "gcp"
    try:
        resolve_secrets()
        validate_environment(cloud)
    except ConfigurationError as exc:
        logger.error("startup_validation_failed", error=str(exc))
        sys.exit(1)

    ignore_regions = [
        r.strip() for r in os.environ.get("IGNORE_REGIONS", "").split(",") if r.strip()
    ]

    project_ids = _get_project_ids()
    if not project_ids:
        logger.error("no_project_ids", msg="Set GCP_PROJECT_ID or GCP_PROJECT_IDS")
        sys.exit(1)

    accounts_mode = os.environ.get("ACCOUNTS_MODE", "single")
    use_multi = accounts_mode == "multi" or len(project_ids) > 1

    structlog.contextvars.bind_contextvars(
        cloud=cloud, mode="multi" if use_multi else "single"
    )
    logger.info("scan_start", projects=project_ids, ignore_regions=ignore_regions)

    scan_errors: list[dict[str, str]] = []
    if use_multi:
        (
            all_findings,
            executive_summary,
            scanned_ids,
            token_summary,
            scan_errors,
            skipped_types,
        ) = _run_multi_project(project_ids, ignore_regions, cloud)
    else:
        all_findings, executive_summary, scanned_ids, token_summary, skipped_types = (
            _run_single_project(project_ids[0], ignore_regions, cloud)
        )
        scan_errors = []

    gcs_bucket = os.environ.get("REPORT_GCS_BUCKET", "").strip()
    previous_report = _load_previous_report(cloud, gcs_bucket)
    all_findings, scan_diff = compare_scans(all_findings, previous_report)

    report = build_report(
        all_findings,
        cloud=cloud,
        executive_summary=executive_summary,
        accounts_scanned=scanned_ids,
        agent_input_tokens=int(token_summary.get("total_input_tokens", 0)),
        agent_output_tokens=int(token_summary.get("total_output_tokens", 0)),
        scan_diff=scan_diff,
        scan_errors=scan_errors,
        skipped_resource_types=skipped_types,
        registry_warnings=get_registry().load_warnings,
    )
    report_url: str | None = None
    if gcs_bucket:
        try:
            report_url = _save_reports_to_gcs(report, gcs_bucket)
        except Exception as exc:  # noqa: BLE001
            logger.error("report_upload_failed_continuing", error=str(exc))
    else:
        save_reports_locally(report)

    # Deliver Slack digest regardless of whether report upload succeeded.
    # report_url=None means the "Full report" button is omitted — that's fine.
    structlog.contextvars.bind_contextvars(scan_id=report["scan_id"])
    payload = build_slack_payload(report, report_url=report_url)
    delivered = notify_all(payload)

    budget_exceeded = executive_summary.startswith("Scan aborted")
    logger.info(
        "scan_complete",
        findings=report["findings_count"],
        total_waste_usd=round(report["total_estimated_waste_usd"], 2),
        budget_exceeded=budget_exceeded,
        slack_delivered=delivered,
    )
    if budget_exceeded:
        sys.exit(2)
    if not delivered:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Project ID resolution
# ---------------------------------------------------------------------------


def _get_project_ids() -> list[str]:
    """Resolve GCP project IDs from environment.

    Priority: ACCOUNTS_CONFIG > GCP_PROJECT_IDS > GCP_PROJECT_ID.
    """
    accounts_mode = os.environ.get("ACCOUNTS_MODE", "single")
    if accounts_mode == "multi":
        raw = os.environ.get("ACCOUNTS_CONFIG", "[]")
        try:
            accounts: list[dict[str, str]] = json.loads(raw)
            if accounts:
                return [a["id"] for a in accounts]
        except (json.JSONDecodeError, KeyError):
            pass

    multi = os.environ.get("GCP_PROJECT_IDS", "").strip()
    if multi:
        return [p.strip() for p in multi.split(",") if p.strip()]

    single = os.environ.get("GCP_PROJECT_ID", "").strip()
    if single:
        return [single]

    return []


def _get_project_names() -> dict[str, str]:
    """Load project display names from ACCOUNTS_CONFIG if available."""
    raw = os.environ.get("ACCOUNTS_CONFIG", "[]")
    try:
        accounts: list[dict[str, str]] = json.loads(raw)
        return {a["id"]: a.get("name", a["id"]) for a in accounts}
    except (json.JSONDecodeError, KeyError):
        return {}


# ---------------------------------------------------------------------------
# Scan runners
# ---------------------------------------------------------------------------


def _run_single_project(
    project_id: str,
    ignore_regions: list[str],
    cloud: str,
) -> tuple[list[ResourceFinding], str, list[str], dict, list[str]]:
    structlog.contextvars.bind_contextvars(account_id=project_id)
    ai_provider = _build_ai_provider(project_id)
    adapter = GCPAdapter(project_id=project_id)
    loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
    findings, summary = loop.run(
        cloud=cloud,
        ignore_regions=ignore_regions,
        accounts=[{"id": project_id, "name": project_id}],
    )
    return (
        findings,
        summary,
        [project_id],
        loop.tracker.summary(),
        adapter.skipped_asset_types,
    )


def _run_multi_project(
    project_ids: list[str],
    ignore_regions: list[str],
    cloud: str,
) -> tuple[
    list[ResourceFinding], str, list[str], dict, list[dict[str, str]], list[str]
]:
    """Scan multiple GCP projects. One adapter + agent loop per project."""
    project_names = _get_project_names()

    all_findings: list[ResourceFinding] = []
    all_summaries: list[str] = []
    scanned_ids: list[str] = []
    scan_errors: list[dict[str, str]] = []
    all_skipped: list[str] = []
    total_input = 0
    total_output = 0
    last_ai_provider = None

    for pid in project_ids:
        name = project_names.get(pid, pid)
        logger.info("scanning_project", project_id=pid, project_name=name)

        try:
            ai_provider = _build_ai_provider(pid)
            last_ai_provider = ai_provider
            adapter = GCPAdapter(project_id=pid)
            loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
            findings, summary = loop.run(
                cloud=cloud,
                ignore_regions=ignore_regions,
                accounts=[{"id": pid, "name": name}],
            )
            all_findings.extend(findings)
            all_summaries.append(f"[{name}] {summary}")
            scanned_ids.append(pid)
            total_input += loop.tracker.total_input_tokens
            total_output += loop.tracker.total_output_tokens
            all_skipped.extend(adapter.skipped_asset_types)
        except PermissionError as exc:
            logger.error("project_scan_failed", project_id=pid, error=str(exc))
            scan_errors.append(
                {"account_id": pid, "account_name": name, "error": str(exc)}
            )

    if len(project_ids) > 1 and all_findings and last_ai_provider is not None:
        logger.info("synthesizing_unified_summary", projects=len(scanned_ids))
        unified, synth_input, synth_output = synthesize_executive_summary(
            all_findings, all_summaries, cloud, last_ai_provider
        )
        total_input += synth_input
        total_output += synth_output
        executive_summary = unified
    else:
        executive_summary = (
            " ".join(all_summaries)
            if all_summaries
            else "No findings across all projects."
        )
    token_summary = {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
    }
    return (
        all_findings,
        executive_summary,
        scanned_ids,
        token_summary,
        scan_errors,
        list(dict.fromkeys(all_skipped)),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _load_previous_report(cloud: str, gcs_bucket: str) -> dict[str, Any] | None:
    """Load the most recent previous report from GCS or local storage."""
    if gcs_bucket:
        try:
            import google.cloud.storage as storage  # type: ignore[import-untyped]

            client = storage.Client()
            bucket = client.bucket(gcs_bucket)
            blobs = sorted(
                (
                    b
                    for b in bucket.list_blobs(prefix=f"reports/{cloud}/")
                    if b.name.endswith(".json")
                ),
                key=lambda b: b.name,
                reverse=True,
            )
            if blobs:
                return json.loads(blobs[0].download_as_bytes())  # type: ignore[no-any-return]
        except Exception as exc:  # noqa: BLE001
            logger.warning("previous_report_load_failed", error=str(exc))
    else:
        from pathlib import Path

        base = Path(os.environ.get("LOCAL_REPORT_DIR", "local_reports")) / cloud
        if base.exists():
            json_files = sorted(base.rglob("*.json"), reverse=True)
            if json_files:
                return json.loads(json_files[0].read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    return None


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
        logger.info("json_report_saved", location=f"gs://{bucket_name}/{json_key}")

        html_blob = bucket.blob(html_key)
        html_blob.upload_from_string(
            build_html_report(report).encode("utf-8"),
            content_type="text/html; charset=utf-8",
        )
        logger.info("html_report_saved", location=f"gs://{bucket_name}/{html_key}")

        url: str | None = _generate_signed_url(html_blob, expiry_seconds)
        if url:
            logger.info("signed_url_generated", expires_in_seconds=expiry_seconds)
        else:
            logger.warning(
                "signed_url_skipped",
                msg="Report uploaded but URL signing unavailable "
                "(no private key on Cloud Run credentials). "
                "Grant roles/iam.serviceAccountTokenCreator to the service account "
                "or use Workload Identity.",
            )
        return url
    except google_exceptions.GoogleAPIError as exc:
        logger.error("gcs_upload_failed", error=str(exc))
        return None


def _generate_signed_url(blob: Any, expiry_seconds: int) -> str | None:
    """
    Generate a v4 signed URL for a GCS blob.

    On Cloud Run / Compute Engine the default credentials carry no private key,
    so we pass the service account email + short-lived access token explicitly.
    The service account must have roles/iam.serviceAccountTokenCreator on itself
    for the signBlob API to work (granted by deploy.sh).
    """
    try:
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())

        sa_email: str | None = getattr(credentials, "service_account_email", None)
        token: str | None = getattr(credentials, "token", None)

        kwargs: dict[str, Any] = {
            "expiration": timedelta(seconds=expiry_seconds),
            "method": "GET",
            "version": "v4",
        }
        if sa_email and token:
            kwargs["service_account_email"] = sa_email
            kwargs["access_token"] = token

        return blob.generate_signed_url(**kwargs)  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001
        logger.warning("signed_url_generation_failed", error=str(exc))
        return None


if __name__ == "__main__":
    main()
