"""
AWS Lambda entrypoint for Argus.

Environment variables (set in CloudFormation template or .env for local):
  IGNORE_REGIONS     Comma-separated regions to exclude from the scan (default: empty = scan all)
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
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from adapters.aws.adapter import AWSAdapter
from core.agent.loop import AgentLoop
from core.models.finding import ResourceFinding
from core.reports.delivery import SlackDeliveryError, post_to_slack
from core.reports.generator import build_report, build_slack_payload
from core.reports.html import build_html_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point. Triggered by EventBridge on a schedule."""
    cloud = "aws"
    ignore_regions = [
        r.strip() for r in os.environ.get("IGNORE_REGIONS", "").split(",") if r.strip()
    ]
    primary_region = os.environ.get("PRIMARY_REGION", "us-east-1")
    accounts_mode = os.environ.get("ACCOUNTS_MODE", "single")

    logger.info(
        "scan_start cloud=%s ignore_regions=%s primary_region=%s mode=%s",
        cloud,
        ignore_regions,
        primary_region,
        accounts_mode,
    )

    ai_provider = _build_ai_provider()

    if accounts_mode == "multi":
        all_findings, executive_summary, account_ids = _run_multi_account(
            ai_provider, ignore_regions, primary_region, cloud
        )
    else:
        all_findings, executive_summary, account_ids = _run_single_account(
            ai_provider, ignore_regions, primary_region, cloud
        )

    report = build_report(
        all_findings,
        cloud=cloud,
        executive_summary=executive_summary,
        accounts_scanned=account_ids,
    )

    s3_bucket = os.environ.get("REPORT_S3_BUCKET", "").strip()
    report_url: str | None = None
    if s3_bucket:
        report_url = _save_reports_to_s3(report, s3_bucket)

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
) -> tuple[list[ResourceFinding], str, list[str]]:
    account_id = _get_current_account_id()
    adapter = AWSAdapter.for_account(account=None, region=primary_region)
    loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
    findings, summary = loop.run(
        cloud=cloud, ignore_regions=ignore_regions, accounts=[{"id": account_id}]
    )
    return findings, summary, [account_id]


def _run_multi_account(
    ai_provider: Any,
    ignore_regions: list[str],
    primary_region: str,
    cloud: str,
) -> tuple[list[ResourceFinding], str, list[str]]:
    raw = os.environ.get("ACCOUNTS_CONFIG", "[]")
    try:
        accounts: list[dict[str, Any]] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ACCOUNTS_CONFIG is not valid JSON: {exc}") from exc

    if not accounts:
        logger.warning(
            "ACCOUNTS_MODE=multi but ACCOUNTS_CONFIG is empty — falling back to single-account mode"
        )
        return _run_single_account(ai_provider, ignore_regions, primary_region, cloud)

    all_findings: list[ResourceFinding] = []
    all_summaries: list[str] = []
    account_ids: list[str] = []

    for account in accounts:
        acct_id = account["id"]
        acct_name = account.get("name", acct_id)
        logger.info("scanning account %s (%s)", acct_name, acct_id)

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
        except (PermissionError, ClientError) as exc:
            logger.error("failed to scan account %s: %s", acct_id, exc)

    executive_summary = (
        " ".join(all_summaries) if all_summaries else "No findings across all accounts."
    )
    return all_findings, executive_summary, account_ids


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
        return sts.get_caller_identity()["Account"]
    except ClientError as exc:
        logger.warning("Could not determine account ID via STS: %s", exc)
        return "unknown"


def _save_reports_to_s3(report: dict[str, Any], bucket: str) -> str | None:
    """Upload JSON + HTML reports to S3. Returns a pre-signed URL for the HTML report."""
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
        logger.info("json report saved to s3://%s/%s", bucket, json_key)

        html_body = build_html_report(report).encode("utf-8")
        s3.put_object(
            Bucket=bucket,
            Key=html_key,
            Body=html_body,
            ContentType="text/html; charset=utf-8",
        )
        logger.info("html report saved to s3://%s/%s", bucket, html_key)

        url: str = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": html_key},
            ExpiresIn=expiry,
        )
        logger.info("pre-signed url generated (expires in %ds)", expiry)
        return url
    except ClientError as exc:
        logger.error("failed to save reports to S3: %s", exc)
        return None
