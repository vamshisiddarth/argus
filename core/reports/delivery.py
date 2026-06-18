from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SlackDeliveryError(Exception):
    """Raised when Slack rejects the webhook payload."""


def post_to_slack(
    payload: dict[str, Any],
    webhook_url: str | None = None,
    dry_run: bool | None = None,
) -> None:
    """
    Post a Slack Block Kit payload to the configured incoming webhook.

    When dry_run is True (or DRY_RUN env var is "true"), logs the payload
    instead of making an HTTP request — useful for local testing.

    Raises SlackDeliveryError if Slack returns a non-OK response.
    """
    resolved_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    resolved_dry_run = (
        dry_run
        if dry_run is not None
        else os.environ.get("DRY_RUN", "").lower() == "true"
    )

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    if resolved_dry_run:
        logger.info(
            "[DRY RUN] Slack payload (not sent):\n%s", json.dumps(payload, indent=2)
        )
        return

    if not resolved_url:
        raise EnvironmentError(
            "SLACK_WEBHOOK_URL is not set. "
            "Export it or pass webhook_url= explicitly."
        )

    req = urllib.request.Request(
        resolved_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise SlackDeliveryError(
            f"Slack webhook returned HTTP {exc.code}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SlackDeliveryError(
            f"Failed to reach Slack webhook: {exc.reason}"
        ) from exc

    if response_text.strip() != "ok":
        raise SlackDeliveryError(f"Unexpected Slack response: {response_text!r}")

    logger.info("Slack report delivered successfully.")


def save_reports_locally(
    report: dict[str, Any],
    base_dir: str | None = None,
) -> str:
    """
    Save JSON + HTML reports to local_reports/ (or base_dir).

    Used as a fallback when no cloud storage bucket is configured —
    keeps local runs consistent with deployed behaviour.
    Returns the absolute path to the HTML file.
    """
    resolved_dir = Path(base_dir or os.environ.get("LOCAL_REPORT_DIR", "local_reports"))
    now = datetime.now(tz=timezone.utc)
    prefix = (
        resolved_dir / report["cloud"] / now.strftime("%Y/%m/%d") / report["scan_id"]
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)

    json_path = prefix.with_suffix(".json")
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("json report saved to %s", json_path)

    from core.reports.html import build_html_report

    html_path = prefix.with_suffix(".html")
    html_path.write_text(build_html_report(report), encoding="utf-8")
    logger.info("html report saved to %s", html_path)

    return str(html_path.resolve())
