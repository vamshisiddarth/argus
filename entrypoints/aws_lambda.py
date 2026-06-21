"""
AWS Lambda entrypoint for Argus.

Environment variables (set in CloudFormation template or .env for local):
  IGNORE_REGIONS     Comma-separated regions to exclude from the scan
                     (default: empty = scan all)
  PRIMARY_REGION     AWS region for boto3 session and Bedrock calls (default: us-east-1)
  DRY_RUN            "true" to skip Slack post and S3 upload (default: false)
  SLACK_WEBHOOK_URL  Slack incoming webhook URL
  AI_PROVIDER        "bedrock" | "anthropic" (default: bedrock)
  ANTHROPIC_API_KEY  Required when AI_PROVIDER=anthropic
  ACCOUNTS_MODE      "single" | "multi" (default: single)
  ACCOUNTS_CONFIG    JSON array of account dicts when ACCOUNTS_MODE=multi
                     e.g. [{"id":"123","name":"prod","role_arn":"arn:..."}]
  REPORT_S3_BUCKET   S3 bucket name for saving full reports (JSON + HTML) (optional)
  REPORT_URL_EXPIRY  Pre-signed URL expiry in seconds (default: 604800 = 7 days)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

from adapters.aws.adapter import AWSAdapter
from core.agent.loop import AgentLoop
from core.log import configure_logging
from core.models.finding import ResourceFinding
from core.reports.comparison import compare_scans
from core.reports.delivery import (
    notify_all,
    save_reports_locally,
)
from core.reports.generator import build_report, build_slack_payload
from core.reports.html import build_html_report
from core.secrets import resolve_secrets
from core.validation import ConfigurationError, validate_environment

configure_logging()
logger = structlog.get_logger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point. Triggered by EventBridge on a schedule."""
    cloud = "aws"
    try:
        resolve_secrets()
        validate_environment(cloud)
    except ConfigurationError as exc:
        logger.error("startup_validation_failed", error=str(exc))
        return {"statusCode": 500, "error": str(exc)}

    ignore_regions = [
        r.strip() for r in os.environ.get("IGNORE_REGIONS", "").split(",") if r.strip()
    ]
    primary_region = os.environ.get("PRIMARY_REGION", "us-east-1")
    accounts_mode = os.environ.get("ACCOUNTS_MODE", "single")

    structlog.contextvars.bind_contextvars(cloud=cloud)
    logger.info(
        "scan_start",
        ignore_regions=ignore_regions,
        primary_region=primary_region,
        mode=accounts_mode,
    )

    ai_provider = _build_ai_provider()

    if accounts_mode == "multi":
        all_findings, executive_summary, account_ids, token_summary = (
            _run_multi_account(ai_provider, ignore_regions, primary_region, cloud)
        )
    else:
        all_findings, executive_summary, account_ids, token_summary = (
            _run_single_account(ai_provider, ignore_regions, primary_region, cloud)
        )

    s3_bucket = os.environ.get("REPORT_S3_BUCKET", "").strip()
    previous_report = _load_previous_report(cloud, s3_bucket)
    all_findings, scan_diff = compare_scans(all_findings, previous_report)

    report = build_report(
        all_findings,
        cloud=cloud,
        executive_summary=executive_summary,
        accounts_scanned=account_ids,
        agent_input_tokens=token_summary.get("total_input_tokens", 0),
        agent_output_tokens=token_summary.get("total_output_tokens", 0),
        scan_diff=scan_diff,
    )
    report_url: str | None = None
    if s3_bucket:
        report_url = _save_reports_to_s3(report, s3_bucket)
    else:
        save_reports_locally(report)

    structlog.contextvars.bind_contextvars(scan_id=report["scan_id"])
    payload = build_slack_payload(report, report_url=report_url)
    notify_all(payload)

    logger.info(
        "scan_complete",
        findings=report["findings_count"],
        total_waste_usd=round(report["total_estimated_waste_usd"], 2),
    )

    return {
        "statusCode": 200,
        "scan_id": report["scan_id"],
        "findings_count": report["findings_count"],
        "total_estimated_waste_usd": report["total_estimated_waste_usd"],
    }


# ---------------------------------------------------------------------------
# Scan runners
# ---------------------------------------------------------------------------


def _run_single_account(
    ai_provider: Any,
    ignore_regions: list[str],
    primary_region: str,
    cloud: str,
) -> tuple[list[ResourceFinding], str, list[str], dict]:
    account_id = _get_current_account_id()
    adapter = AWSAdapter.for_account(account=None, region=primary_region)
    loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
    findings, summary = loop.run(
        cloud=cloud, ignore_regions=ignore_regions, accounts=[{"id": account_id}]
    )
    return findings, summary, [account_id], loop.tracker.summary()


def _run_multi_account(
    ai_provider: Any,
    ignore_regions: list[str],
    primary_region: str,
    cloud: str,
) -> tuple[list[ResourceFinding], str, list[str], dict]:
    raw = os.environ.get("ACCOUNTS_CONFIG", "[]")
    try:
        accounts: list[dict[str, Any]] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ACCOUNTS_CONFIG is not valid JSON: {exc}") from exc

    if not accounts:
        logger.warning(
            "ACCOUNTS_MODE=multi but ACCOUNTS_CONFIG is empty "
            "— falling back to single-account mode"
        )
        return _run_single_account(ai_provider, ignore_regions, primary_region, cloud)

    all_findings: list[ResourceFinding] = []
    all_summaries: list[str] = []
    account_ids: list[str] = []
    total_input = 0
    total_output = 0

    for account in accounts:
        acct_id = account["id"]
        acct_name = account.get("name", acct_id)
        logger.info("scanning_account", account_id=acct_id, account_name=acct_name)

        try:
            adapter = AWSAdapter.for_account(account=account, region=primary_region)
            loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
            findings, summary = loop.run(
                cloud=cloud,
                ignore_regions=ignore_regions,
                accounts=[{"id": acct_id, "name": acct_name}],
            )
            all_findings.extend(findings)
            all_summaries.append(f"[{acct_name}] {summary}")
            account_ids.append(acct_id)
            total_input += loop.tracker.total_input_tokens
            total_output += loop.tracker.total_output_tokens
        except (PermissionError, ClientError) as exc:
            logger.error("account_scan_failed", account_id=acct_id, error=str(exc))

    executive_summary = (
        " ".join(all_summaries) if all_summaries else "No findings across all accounts."
    )
    token_summary = {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
    }
    return all_findings, executive_summary, account_ids, token_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_ai_provider() -> Any:
    provider_name = os.environ.get("AI_PROVIDER", "bedrock").lower()
    if provider_name == "anthropic":
        from ai.anthropic import AnthropicProvider

        return AnthropicProvider()
    from ai.bedrock import BedrockProvider

    return BedrockProvider()


def _get_current_account_id() -> str:
    try:
        sts = boto3.client("sts")
        return str(sts.get_caller_identity()["Account"])
    except ClientError as exc:
        logger.warning("sts_get_account_id_failed", error=str(exc))
        return "unknown"


def _load_previous_report(cloud: str, s3_bucket: str) -> dict[str, Any] | None:
    """Load the most recent previous report from S3 or local storage."""
    if s3_bucket:
        try:
            s3 = boto3.client("s3")
            resp = s3.list_objects_v2(
                Bucket=s3_bucket,
                Prefix=f"reports/{cloud}/",
                MaxKeys=1000,
            )
            json_keys = sorted(
                (
                    obj["Key"]
                    for obj in resp.get("Contents", [])
                    if obj["Key"].endswith(".json")
                ),
                reverse=True,
            )
            if json_keys:
                body = s3.get_object(Bucket=s3_bucket, Key=json_keys[0])["Body"].read()
                return json.loads(body)  # type: ignore[no-any-return]
        except ClientError as exc:
            logger.warning("previous_report_load_failed", error=str(exc))
    else:
        return _load_previous_report_local(cloud)
    return None


def _load_previous_report_local(cloud: str) -> dict[str, Any] | None:
    """Load the most recent previous report from local_reports/."""
    from pathlib import Path

    base = Path(os.environ.get("LOCAL_REPORT_DIR", "local_reports")) / cloud
    if not base.exists():
        return None
    json_files = sorted(base.rglob("*.json"), reverse=True)
    if json_files:
        return json.loads(json_files[0].read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    return None


def _save_reports_to_s3(report: dict[str, Any], bucket: str) -> str | None:
    """Upload JSON + HTML reports to S3. Returns a pre-signed URL for the HTML."""
    now = datetime.now(tz=timezone.utc)
    prefix = f"reports/{report['cloud']}/{now.strftime('%Y/%m/%d')}/{report['scan_id']}"
    json_key = f"{prefix}.json"
    html_key = f"{prefix}.html"
    expiry = int(os.environ.get("REPORT_URL_EXPIRY", "604800"))

    try:
        s3 = boto3.client("s3")

        s3.put_object(
            Bucket=bucket,
            Key=json_key,
            Body=json.dumps(report, indent=2, default=str).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("json_report_saved", location=f"s3://{bucket}/{json_key}")

        html_body = build_html_report(report).encode("utf-8")
        s3.put_object(
            Bucket=bucket,
            Key=html_key,
            Body=html_body,
            ContentType="text/html; charset=utf-8",
        )
        logger.info("html_report_saved", location=f"s3://{bucket}/{html_key}")

        url: str = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": html_key},
            ExpiresIn=expiry,
        )
        logger.info("presigned_url_generated", expires_in_seconds=expiry)
        return url
    except ClientError as exc:
        logger.error("s3_upload_failed", error=str(exc))
        return None
