from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.models.finding import ResourceFinding

# Maximum findings shown as individual rows in the Slack digest
SLACK_DIGEST_LIMIT = 5


def build_report(
    findings: list[ResourceFinding],
    cloud: str,
    executive_summary: str,
    accounts_scanned: list[str] | None = None,
    agent_input_tokens: int = 0,
    agent_output_tokens: int = 0,
    scan_diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Convert a list of ResourceFinding objects into the canonical JSON report.
    Findings are sorted by estimated_monthly_cost descending before serialising.
    """
    sorted_findings = sorted(
        findings, key=lambda f: f.estimated_monthly_cost, reverse=True
    )
    total_waste = sum(f.estimated_monthly_cost for f in sorted_findings)

    return {
        "schema_version": "1.0",
        "scan_id": str(uuid.uuid4()),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "cloud": cloud,
        "accounts_scanned": accounts_scanned or [],
        "total_estimated_waste_usd": round(total_waste, 2),
        "findings_count": len(sorted_findings),
        "findings": [f.to_dict() for f in sorted_findings],
        "executive_summary": executive_summary,
        "agent_input_tokens": agent_input_tokens,
        "agent_output_tokens": agent_output_tokens,
        "estimated_agent_cost_usd": _estimate_cost(
            agent_input_tokens, agent_output_tokens
        ),
        "scan_diff": scan_diff,
    }


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost_per_m = 3.0
    output_cost_per_m = 15.0
    cost = (input_tokens / 1_000_000 * input_cost_per_m) + (
        output_tokens / 1_000_000 * output_cost_per_m
    )
    return round(cost, 4)


def build_slack_payload(
    report: dict[str, Any],
    report_url: str | None = None,
) -> dict[str, Any]:
    """
    Build a compact Slack Block Kit digest.

    Shows stats + AI summary + top findings as a one-line-per-finding table.
    Full AI reasoning lives in the HTML report linked via report_url.
    """
    cloud = report["cloud"].upper()
    total = report["total_estimated_waste_usd"]
    count = report["findings_count"]
    generated_at = report["generated_at"][:10]  # YYYY-MM-DD
    accounts = len(report.get("accounts_scanned", []))

    _PRIORITY_EMOJI = {
        "HIGH": ":red_circle:",
        "MEDIUM": ":large_yellow_circle:",
        "LOW": ":large_green_circle:",
    }

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Argus — {cloud} Waste Report ({generated_at})",
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f":money_with_wings: *${total:,.2f}/month* estimated waste",
                },
                {
                    "type": "mrkdwn",
                    "text": (
                        f":bar_chart: *{count}* idle "
                        f"resource{'s' if count != 1 else ''} across "
                        f"*{accounts}* account{'s' if accounts != 1 else ''}"
                    ),
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"_{report['executive_summary']}_",
            },
        },
        {"type": "divider"},
    ]

    top = report["findings"][:SLACK_DIGEST_LIMIT]
    if top:
        lines = ["*Top findings*"]
        for finding in top:
            cost = finding["estimated_monthly_cost"]
            priority = (finding.get("priority") or "low").upper()
            emoji = _PRIORITY_EMOJI.get(priority, ":white_circle:")
            label = finding.get("name") or finding["resource_id"]
            rtype = finding["resource_type"]
            lines.append(f"{emoji} `{label}` · {rtype} · *${cost:,.2f}/mo*")

        remaining = count - SLACK_DIGEST_LIMIT
        if remaining > 0:
            lines.append(
                f":white_circle: _+{remaining} more "
                f"finding{'s' if remaining != 1 else ''} in the full report_"
            )

        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}
        )
        blocks.append({"type": "divider"})

    actions: list[dict[str, Any]] = []
    if report_url:
        actions.append(
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": ":page_facing_up: Full report (HTML)",
                },
                "url": report_url,
                "style": "primary",
            }
        )
    actions.append(
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "vamshisiddarth/argus"},
            "url": "https://github.com/vamshisiddarth/argus",
        }
    )
    blocks.append({"type": "actions", "elements": actions})

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Scan ID: `{report['scan_id']}`"}],
        }
    )

    return {"blocks": blocks}
