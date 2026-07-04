"""
Converts a ChangeProposal + integrations config into Jira issue fields.

Stores a compact snapshot fingerprint in the issue description footer so
the tracker can detect when the analysis has changed on subsequent scans.
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
        f"(${proposal.estimated_monthly_cost_usd:.0f}/mo)"
    )

    description = _build_description(proposal, report_url=report_url)
    priority_name = priority_map.get(f.priority, "Medium")
    labels = list(default_labels) + [dedup_label]

    return {
        "project": {"key": project},
        "summary": summary,
        "description": _adf_doc(description),
        "issuetype": {"name": issue_type},
        "priority": {"name": priority_name},
        "labels": labels,
    }


def build_update_comment(
    proposal: ChangeProposal,
    stored: dict[str, Any],
) -> str:
    """Plain-text comment body describing what changed since the last scan."""
    f = proposal.finding
    current = fingerprint(proposal)
    lines = [f"[Argus update — {date.today()}]"]

    if stored.get("cost") != current["cost"]:
        lines.append(
            f"Cost: ${stored.get('cost', '?')}/mo → ${current['cost']}/mo"
        )
    if stored.get("priority") != current["priority"]:
        lines.append(
            f"Priority: {stored.get('priority', '?')} → {current['priority']}"
        )
    if stored.get("reason_hash") != current["reason_hash"]:
        lines.append(f"AI says: \"{f.waste_reason[:120]}\"")

    return "\n".join(lines)


def fingerprint(proposal: ChangeProposal) -> dict[str, Any]:
    """Compact snapshot of the three fields that trigger a comment on change."""
    return {
        "cost": round(proposal.estimated_monthly_cost_usd, 0),
        "priority": proposal.finding.priority,
        "reason_hash": hashlib.md5(
            proposal.finding.waste_reason[:120].encode()
        ).hexdigest()[:6],
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
    raw = description_text[start + len(_SNAPSHOT_MARKER):end].strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _build_description(
    proposal: ChangeProposal,
    report_url: str | None,
) -> str:
    f = proposal.finding
    p = proposal.policy
    snap = json.dumps(fingerprint(proposal))

    lines = [
        "## Finding",
        f"Resource: {f.name or f.resource_id} ({f.resource_type}, {f.region})",
        f"Estimated monthly cost: ${proposal.estimated_monthly_cost_usd:.2f}",
        f"Action: {p.action}",
        "",
        "## Why Argus flagged this",
        f.waste_reason,
        "",
        "## Recommendation",
        f.recommendation,
        "",
        "## Runbook",
        f"```\n{proposal.runbook}\n```",
        "",
        "## Policy",
        f"Policy: {p.policy_id} (weight: {p.weight})",
        f"Source: {p.source_file}",
    ]

    if report_url:
        lines += ["", "## Full report", report_url]

    lines += [
        "",
        "---",
        f"{_SNAPSHOT_MARKER} {snap} {_SNAPSHOT_END}",
    ]

    return "\n".join(lines)


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


def _adf_doc(text: str) -> dict[str, Any]:
    """Wrap markdown-ish text in a minimal ADF doc (single code block)."""
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }
