from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from core.models.finding import ResourceFinding
from core.registry import get_registry
from core.registry.registry import ResourceRegistry

if TYPE_CHECKING:
    from ai.base import AIProvider


def _registry() -> ResourceRegistry:
    return get_registry()


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
    scan_errors: list[dict[str, str]] | None = None,
    skipped_resource_types: list[str] | None = None,
) -> dict[str, Any]:
    """
    Convert a list of ResourceFinding objects into the canonical JSON report.
    Findings are sorted by estimated_monthly_cost descending before serialising.

    scan_errors: list of {"account_id": ..., "account_name": ..., "error": ...}
        for accounts/projects/subscriptions that failed to scan.
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
        "scan_errors": scan_errors or [],
        "skipped_resource_types": skipped_resource_types or [],
    }


def synthesize_executive_summary(
    findings: list[ResourceFinding],
    per_account_summaries: list[str],
    cloud: str,
    ai_provider: "AIProvider",
) -> tuple[str, int, int]:
    """
    Generate a single unified executive summary across all accounts/projects.

    Called once after all per-account scans complete, with the full merged
    findings list. Returns (summary_text, input_tokens, output_tokens).

    Falls back to joining per_account_summaries if the AI call fails.
    """
    from ai.base import Message

    if not findings and not per_account_summaries:
        return f"No idle resources found across any {cloud.upper()} accounts.", 0, 0

    total_waste = sum(f.estimated_monthly_cost for f in findings)
    top_findings = sorted(
        findings, key=lambda f: f.estimated_monthly_cost, reverse=True
    )[:10]

    findings_digest = json.dumps(
        [
            {
                "account": getattr(f, "account_name", None) or f.cloud,
                "resource_id": f.resource_id,
                "name": f.name,
                "type": _registry().display_name(f.resource_type),
                "region": f.region,
                "cost_usd": round(f.estimated_monthly_cost, 2),
                "priority": f.priority,
                "waste_reason": f.waste_reason,
            }
            for f in top_findings
        ],
        indent=2,
    )

    n_accounts = len({s.split("]")[0].lstrip("[") for s in per_account_summaries if s})
    prompt = (  # noqa: E501
        f"You are writing the executive summary section of a cloud cost report"
        f" for engineering leadership.\n\n"
        f"Scan context:\n"
        f"- Cloud: {cloud.upper()}\n"
        f"- Accounts/projects scanned: {n_accounts}\n"
        f"- Total findings: {len(findings)}\n"
        f"- Total estimated waste: ${total_waste:,.2f}/month\n\n"
        f"Top findings across all accounts (by cost):\n{findings_digest}\n\n"
        f"Per-account summaries from individual scans:\n"
        f"{chr(10).join(per_account_summaries)}\n\n"
        f"Write a 3-5 sentence executive summary that:\n"
        f"1. States the total waste and number of accounts scanned upfront\n"
        f"2. Identifies which account/project has the largest waste and"
        f" what the top resource type is\n"
        f"3. Highlights any cross-account patterns"
        f' (e.g. "idle RDS instances appear in all three environments")\n'
        f"4. Ends with a single clear action recommendation for the team\n\n"
        f"Write only the summary text."
        f" No headings, no bullet points, no markdown. Plain prose."
    )

    try:
        response = ai_provider.chat(
            messages=[Message(role="user", text=prompt)],
            tools=[],
            system_prompt=None,
        )
        text = (response.text or "").strip()
        if text:
            return text, response.input_tokens, response.output_tokens
    except Exception:  # noqa: BLE001
        pass

    # Fallback: join per-account summaries
    fallback = (
        " ".join(per_account_summaries)
        if per_account_summaries
        else f"No idle resources found across {cloud.upper()} accounts."
    )
    return fallback, 0, 0


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

    skipped_types = report.get("skipped_resource_types") or []
    if skipped_types:
        short_names = [t.split("/")[-1] for t in skipped_types]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":information_source: *Skipped {len(skipped_types)} resource "
                        f"type{'s' if len(skipped_types) != 1 else ''} "
                        f"(API not enabled in project):* "
                        + ", ".join(f"`{n}`" for n in short_names)
                    ),
                },
            }
        )
        blocks.append({"type": "divider"})

    scan_errors = report.get("scan_errors") or []
    if scan_errors:
        total_attempted = accounts + len(scan_errors)
        error_lines = [
            f":warning: *Partial scan — {accounts}/{total_attempted} "
            f"account{'s' if total_attempted != 1 else ''} succeeded*"
        ]
        for err in scan_errors:
            name = err.get("account_name") or err.get("account_id", "unknown")
            reason = err.get("error", "unknown error")
            error_lines.append(f"• `{name}` failed: {reason}")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(error_lines)},
            }
        )
        blocks.append({"type": "divider"})

    top = report["findings"][:SLACK_DIGEST_LIMIT]
    if top:
        lines = ["*Top findings*"]
        for finding in top:
            cost = finding["estimated_monthly_cost"]
            priority = (finding.get("priority") or "low").upper()
            emoji = _PRIORITY_EMOJI.get(priority, ":white_circle:")
            label = finding.get("name") or finding["resource_id"]
            rtype = _registry().display_name(finding["resource_type"])
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
