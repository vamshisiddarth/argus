from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NotificationDeliveryError(Exception):
    """Raised when a notification provider fails to deliver."""


class SlackDeliveryError(NotificationDeliveryError):
    """Raised when Slack rejects the webhook payload."""


class TeamsDeliveryError(NotificationDeliveryError):
    """Raised when Teams rejects the webhook payload."""


class WebhookDeliveryError(NotificationDeliveryError):
    """Raised when a generic webhook call fails."""


# ---------------------------------------------------------------------------
# NotificationProvider ABC
# ---------------------------------------------------------------------------


class NotificationProvider(ABC):
    @abstractmethod
    def notify(self, payload: dict[str, Any]) -> None: ...


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


class SlackNotificationProvider(NotificationProvider):
    def __init__(self, webhook_url: str | None = None) -> None:
        self._url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")

    def notify(self, payload: dict[str, Any]) -> None:
        if not self._url:
            raise EnvironmentError(
                "SLACK_WEBHOOK_URL is not set. "
                "Export it or pass webhook_url= explicitly."
            )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url,
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

        logger.info("slack_report_delivered")


# ---------------------------------------------------------------------------
# Microsoft Teams (Office 365 Incoming Webhook)
# ---------------------------------------------------------------------------


class TeamsNotificationProvider(NotificationProvider):
    def __init__(self, webhook_url: str | None = None) -> None:
        self._url = webhook_url or os.environ.get("TEAMS_WEBHOOK_URL", "")

    def notify(self, payload: dict[str, Any]) -> None:
        if not self._url:
            raise EnvironmentError(
                "TEAMS_WEBHOOK_URL is not set. "
                "Export it or pass webhook_url= explicitly."
            )
        teams_payload = self._to_teams_card(payload)
        body = json.dumps(teams_payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            raise TeamsDeliveryError(
                f"Teams webhook returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TeamsDeliveryError(
                f"Failed to reach Teams webhook: {exc.reason}"
            ) from exc

        logger.info("teams_report_delivered")

    def _to_teams_card(self, slack_payload: dict[str, Any]) -> dict[str, Any]:
        text_parts: list[str] = []
        for block in slack_payload.get("blocks", []):
            if block.get("type") == "section":
                text_obj = block.get("text", {})
                text_parts.append(text_obj.get("text", ""))
            elif block.get("type") == "header":
                text_obj = block.get("text", {})
                text_parts.append(f"**{text_obj.get('text', '')}**")

        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "Argus Cost Report",
            "themeColor": "0076D7",
            "title": "Argus Cost Optimization Report",
            "text": "\n\n".join(text_parts),
        }


# ---------------------------------------------------------------------------
# Generic Webhook (HTTP POST with raw JSON)
# ---------------------------------------------------------------------------


class WebhookNotificationProvider(NotificationProvider):
    def __init__(self, webhook_url: str | None = None) -> None:
        self._url = webhook_url or os.environ.get("WEBHOOK_URL", "")

    def notify(self, payload: dict[str, Any]) -> None:
        if not self._url:
            raise EnvironmentError(
                "WEBHOOK_URL is not set. " "Export it or pass webhook_url= explicitly."
            )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            raise WebhookDeliveryError(
                f"Webhook returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise WebhookDeliveryError(
                f"Failed to reach webhook: {exc.reason}"
            ) from exc

        logger.info("webhook_report_delivered")


# ---------------------------------------------------------------------------
# Provider registry + dispatcher
# ---------------------------------------------------------------------------

_PROVIDER_MAP: dict[str, type[NotificationProvider]] = {
    "slack": SlackNotificationProvider,
    "teams": TeamsNotificationProvider,
    "webhook": WebhookNotificationProvider,
}


def build_notification_providers() -> list[NotificationProvider]:
    raw = os.environ.get("NOTIFICATION_PROVIDER", "slack")
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    providers: list[NotificationProvider] = []
    for name in names:
        cls = _PROVIDER_MAP.get(name)
        if cls is None:
            logger.warning("unknown_notification_provider", provider=name)
            continue
        providers.append(cls())
    return providers


def notify_all(payload: dict[str, Any], dry_run: bool | None = None) -> None:
    resolved_dry_run = (
        dry_run
        if dry_run is not None
        else os.environ.get("DRY_RUN", "").lower() == "true"
    )

    if resolved_dry_run:
        logger.info(
            "dry_run_notification_skipped",
            payload_preview=json.dumps(payload, indent=2)[:500],
        )
        return

    providers = build_notification_providers()
    for provider in providers:
        try:
            provider.notify(payload)
        except (NotificationDeliveryError, OSError) as exc:
            logger.error(
                "notification_delivery_failed",
                provider=type(provider).__name__,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Legacy function — delegates to notify_all for backward compatibility
# ---------------------------------------------------------------------------


def post_to_slack(
    payload: dict[str, Any],
    webhook_url: str | None = None,
    dry_run: bool | None = None,
) -> None:
    resolved_dry_run = (
        dry_run
        if dry_run is not None
        else os.environ.get("DRY_RUN", "").lower() == "true"
    )

    if resolved_dry_run:
        logger.info(
            "[DRY RUN] Slack payload (not sent):\n%s", json.dumps(payload, indent=2)
        )
        return

    provider = SlackNotificationProvider(webhook_url=webhook_url)
    provider.notify(payload)


# ---------------------------------------------------------------------------
# Local report saving (unchanged)
# ---------------------------------------------------------------------------


def save_reports_locally(
    report: dict[str, Any],
    base_dir: str | None = None,
) -> str:
    from core.reports.export import export_pdf, export_pptx, get_report_formats

    resolved_dir = Path(base_dir or os.environ.get("LOCAL_REPORT_DIR", "local_reports"))
    now = datetime.now(tz=timezone.utc)
    prefix = (
        resolved_dir / report["cloud"] / now.strftime("%Y/%m/%d") / report["scan_id"]
    )
    prefix.parent.mkdir(parents=True, exist_ok=True)

    formats = get_report_formats()
    result_path = str(prefix)

    if "json" in formats:
        json_path = prefix.with_suffix(".json")
        json_path.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        logger.info("json_report_saved", path=str(json_path))

    if "html" in formats:
        from core.reports.html import build_html_report

        html_path = prefix.with_suffix(".html")
        html_path.write_text(build_html_report(report), encoding="utf-8")
        logger.info("html_report_saved", path=str(html_path))
        result_path = str(html_path.resolve())

    if "pdf" in formats:
        try:
            export_pdf(report, prefix)
        except ImportError as exc:
            logger.warning("pdf_export_skipped", reason=str(exc))

    if "pptx" in formats:
        try:
            export_pptx(report, prefix)
        except ImportError as exc:
            logger.warning("pptx_export_skipped", reason=str(exc))

    return result_path
