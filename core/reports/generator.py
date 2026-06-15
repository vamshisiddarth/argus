from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.models.finding import ResourceFinding

# Top N findings shown in the Slack summary block
TOP_FINDINGS_LIMIT = 10


def build_report(
    findings: list[ResourceFinding],
    cloud: str,
    executive_summary: str,
    accounts_scanned: list[str] | None = None,
) -> dict[str, Any]:
    """
    Convert a list of ResourceFinding objects into the canonical JSON report.
    Findings are sorted by estimated_monthly_cost descending before serialising.
    """
    sorted_findings = sorted(findings, key=lambda f: f.estimated_monthly_cost, reverse=True)
    total_waste = sum(f.estimated_monthly_cost for f in sorted_findings)

    return {
        "scan_id": str(uuid.uuid4()),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "cloud": cloud,
        "accounts_scanned": accounts_scanned or [],
        "total_estimated_waste_usd": round(total_waste, 2),
        "findings_count": len(sorted_findings),
        "findings": [f.to_dict() for f in sorted_findings],
        "executive_summary": executive_summary,
    }


def build_slack_payload(report: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a JSON report into a Slack Block Kit message payload.
    Shows the executive summary and the top findings ranked by cost.
    """
    cloud = report["cloud"].upper()
    total = report["total_estimated_waste_usd"]
    count = report["findings_count"]
    generated_at = report["generated_at"][:10]  # YYYY-MM-DD

    header_text = f":money_with_wings: *Argus — {cloud} Waste Report* ({generated_at})"
    summary_text = (
        f"*{count} idle resource{'s' if count != 1 else ''}* found "
        f"costing an estimated *${total:,.2f}/month*.\n\n"
        f"{report['executive_summary']}"
    )

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Argus — {cloud} Waste Report ({generated_at})"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary_text}},
        {"type": "divider"},
    ]

    top = report["findings"][:TOP_FINDINGS_LIMIT]
    for i, finding in enumerate(top, start=1):
        cost = finding["estimated_monthly_cost"]
        priority = finding["priority"].upper()
        priority_emoji = {"HIGH": ":red_circle:", "MEDIUM": ":large_yellow_circle:", "LOW": ":large_green_circle:"}.get(priority, ":white_circle:")
        label = finding.get("name") or finding["resource_id"]
        resource_type = finding["resource_type"]
        region = finding["region"]

        finding_text = (
            f"{priority_emoji} *{i}. {label}* (`{resource_type}` · {region})\n"
            f"*Cost:* ${cost:,.2f}/mo · *Priority:* {priority}\n"
            f"*Why:* {finding['waste_reason']}\n"
            f"*Action:* {finding['recommendation']}"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": finding_text}})

    if len(report["findings"]) > TOP_FINDINGS_LIMIT:
        remaining = len(report["findings"]) - TOP_FINDINGS_LIMIT
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{remaining} more finding{'s' if remaining != 1 else ''} in the full report._"}],
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Scan ID: `{report['scan_id']}`"}],
    })

    return {"blocks": blocks}
