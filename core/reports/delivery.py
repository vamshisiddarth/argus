from __future__ import annotations

import json
import logging
import os
import urllib.request
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
    resolved_dry_run = dry_run if dry_run is not None else os.environ.get("DRY_RUN", "").lower() == "true"

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    if resolved_dry_run:
        logger.info("[DRY RUN] Slack payload (not sent):\n%s", json.dumps(payload, indent=2))
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
        raise SlackDeliveryError(
            f"Unexpected Slack response: {response_text!r}"
        )

    logger.info("Slack report delivered successfully.")
