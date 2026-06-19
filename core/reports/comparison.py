from __future__ import annotations

from typing import Any

from core.models.finding import ResourceFinding


def compare_scans(
    current_findings: list[ResourceFinding],
    previous_report: dict[str, Any] | None,
) -> tuple[list[ResourceFinding], dict[str, Any]]:
    """
    Compare current findings against a previous report and label each finding's status.

    Returns:
        (labelled_findings, diff_summary)
        labelled_findings: current findings with status set to "new" or "recurring"
        diff_summary: dict with new/recurring/resolved counts
                      and resolved_resource_ids
    """
    if not previous_report:
        for f in current_findings:
            f.status = "new"
        return current_findings, {
            "previous_scan_id": None,
            "new_findings": len(current_findings),
            "recurring_findings": 0,
            "resolved_findings": 0,
            "resolved_resource_ids": [],
        }

    prev_resource_ids = {f["resource_id"] for f in previous_report.get("findings", [])}
    current_resource_ids = {f.resource_id for f in current_findings}

    for f in current_findings:
        f.status = "recurring" if f.resource_id in prev_resource_ids else "new"

    resolved_ids = sorted(prev_resource_ids - current_resource_ids)

    new_count = sum(1 for f in current_findings if f.status == "new")
    recurring_count = sum(1 for f in current_findings if f.status == "recurring")

    return current_findings, {
        "previous_scan_id": previous_report.get("scan_id"),
        "new_findings": new_count,
        "recurring_findings": recurring_count,
        "resolved_findings": len(resolved_ids),
        "resolved_resource_ids": resolved_ids,
    }
