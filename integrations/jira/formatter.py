"""
Converts a ChangeProposal into Jira issue fields (ADF format).

Description structure:
  h2 Finding
    resource details, cost, action
  h2 Key Metrics
    table of metrics_summary values
  h2 Why Argus Flagged This
    AI waste_reason
  h2 Recommendation
    AI recommendation
  h2 Runbook
    code block with CLI commands
  h2 Policy
    policy_id, weight, source file
  h2 Full Report  (if report_url given)
  --- snapshot footer (machine-readable fingerprint for diff-on-update)

Snapshot fingerprint stored in description footer enables dedup and
change detection on subsequent scans without a separate DB.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from core.remediation.models import ChangeProposal

_SNAPSHOT_MARKER = "<!-- argus-snapshot:"
_SNAPSHOT_END = "-->"


def build_issue_fields(
    proposal: ChangeProposal,
    *,
    project: str,
    issue_type: str,
    default_labels: list[str],
    priority_map: dict[str, str],
    dedup_label: str,
    report_url: str | None = None,
) -> dict[str, Any]:
    """Return the Jira issue fields dict ready to POST to /rest/api/3/issue."""
    f = proposal.finding
    p = proposal.policy

    summary = (
        f"[Argus] {_action_verb(p.action)} {f.name or f.resource_id} "
        f"(${proposal.estimated_monthly_cost_usd:.0f}/mo · {f.priority} priority)"
    )

    priority_name = priority_map.get(f.priority, "Medium")
    labels = list(default_labels) + [
        dedup_label,
        f"argus-priority-{f.priority}",
        f"argus-action-{p.action}",
    ]

    return {
        "project": {"key": project},
        "summary": summary,
        "description": _build_adf_description(proposal, report_url=report_url),
        "issuetype": {"name": issue_type},
        "priority": {"name": priority_name},
        "labels": labels,
    }


def build_update_comment(
    proposal: ChangeProposal,
    stored: dict[str, Any],
) -> dict[str, Any]:
    """ADF comment body describing what changed since the last scan."""
    f = proposal.finding
    current = fingerprint(proposal)
    lines = [f"Argus re-scan update — {date.today()}"]

    if stored.get("cost") != current["cost"]:
        lines.append(f"Cost: ${stored.get('cost', '?')}/mo → ${current['cost']}/mo")
    if stored.get("priority") != current["priority"]:
        lines.append(f"Priority: {stored.get('priority', '?')} → {current['priority']}")
    if stored.get("reason_hash") != current["reason_hash"]:
        lines.append(f'AI reasoning updated: "{f.waste_reason[:160]}"')
    if stored.get("proposal_id") != current.get("proposal_id"):
        lines.append(f"Proposal ID: {current.get('proposal_id', 'unknown')}")

    return _adf_paragraph("\n".join(lines))


def fingerprint(proposal: ChangeProposal) -> dict[str, Any]:
    """Compact snapshot of fields that trigger a comment on change."""
    return {
        "proposal_id": proposal.proposal_id,
        "cost": round(proposal.estimated_monthly_cost_usd, 0),
        "priority": proposal.finding.priority,
        "reason_hash": hashlib.md5(
            proposal.finding.waste_reason[:120].encode()
        ).hexdigest()[:8],
    }


def extract_snapshot(description_text: str) -> dict[str, Any] | None:
    """
    Parse the argus-snapshot JSON from the issue description footer.
    Returns None if not present (ticket created by an older version).
    """
    start = description_text.find(_SNAPSHOT_MARKER)
    if start == -1:
        return None
    end = description_text.find(_SNAPSHOT_END, start)
    if end == -1:
        return None
    raw = description_text[start + len(_SNAPSHOT_MARKER) : end].strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


# ------------------------------------------------------------------
# ADF builder
# ------------------------------------------------------------------


def _build_adf_description(
    proposal: ChangeProposal,
    report_url: str | None,
) -> dict[str, Any]:
    f = proposal.finding
    p = proposal.policy
    snap = json.dumps(fingerprint(proposal))

    content: list[dict[str, Any]] = []

    # h2 Finding
    content.append(_adf_heading("Finding", level=2))
    content.append(
        _adf_paragraph(
            f"Resource:  {f.name or f.resource_id}\n"
            f"Type:      {f.resource_type}\n"
            f"Cloud:     {f.cloud.upper()}\n"
            f"Region:    {f.region}\n"
            f"Cost:      ${proposal.estimated_monthly_cost_usd:.2f}/mo\n"
            f"Priority:  {f.priority.upper()}\n"
            f"Action:    {p.action}\n"
            f"Proposal:  {proposal.proposal_id}"
        )
    )

    # h2 Key Metrics (only if present)
    if f.metrics_summary:
        content.append(_adf_heading("Key Metrics", level=2))
        rows = [
            [
                _adf_text(k),
                _adf_text(str(round(v, 4)) if isinstance(v, float) else str(v)),
            ]
            for k, v in sorted(f.metrics_summary.items())
        ]
        content.append(_adf_table(["Metric", "Value"], rows))

    # h2 Why Argus Flagged This
    content.append(_adf_heading("Why Argus Flagged This", level=2))
    content.append(_adf_paragraph(f.waste_reason))

    # h2 Recommendation
    content.append(_adf_heading("Recommendation", level=2))
    content.append(_adf_paragraph(f.recommendation))
    if proposal.resize_recommendation:
        content.append(_adf_paragraph(f"Rightsizing: {proposal.resize_recommendation}"))

    # h2 Runbook
    content.append(_adf_heading("Runbook", level=2))
    content.append(
        _adf_paragraph(
            "⚠  Human approval required. Argus does not execute these commands."
        )
    )
    content.append(_adf_code_block(proposal.runbook))

    # h2 Policy
    content.append(_adf_heading("Policy", level=2))
    content.append(
        _adf_paragraph(
            f"Policy ID:   {p.policy_id}\n"
            f"Weight:      {p.weight}\n"
            f"Source:      {p.source_file}"
        )
    )

    # h2 Full Report
    if report_url:
        content.append(_adf_heading("Full Report", level=2))
        content.append(_adf_paragraph(report_url))

    # Machine-readable snapshot footer
    content.append(_adf_paragraph(f"{_SNAPSHOT_MARKER} {snap} {_SNAPSHOT_END}"))

    return {"version": 1, "type": "doc", "content": content}


# ------------------------------------------------------------------
# ADF node helpers
# ------------------------------------------------------------------


def _adf_heading(text: str, level: int) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [{"type": "text", "text": text}],
    }


def _adf_paragraph(text: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def _adf_code_block(text: str) -> dict[str, Any]:
    return {
        "type": "codeBlock",
        "attrs": {"language": "bash"},
        "content": [{"type": "text", "text": text}],
    }


def _adf_text(text: str) -> dict[str, Any]:
    return {"type": "tableCell", "content": [_adf_paragraph(text)]}


def _adf_table(
    headers: list[str],
    rows: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    header_row = {
        "type": "tableRow",
        "content": [
            {
                "type": "tableHeader",
                "content": [_adf_paragraph(h)],
            }
            for h in headers
        ],
    }
    body_rows = [{"type": "tableRow", "content": row} for row in rows]
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": [header_row, *body_rows],
    }


def _action_verb(action: str) -> str:
    return {
        "delete": "Delete",
        "resize": "Resize",
        "stop": "Stop",
        "snapshot_delete": "Snapshot & delete",
        "reduce_replicas": "Reduce replicas for",
        "reduce_nodes": "Reduce nodes for",
        "archive": "Archive",
        "convert_spot": "Convert to Spot",
    }.get(action, action.capitalize())
