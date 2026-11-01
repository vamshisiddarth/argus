"""
Evidence, risk and check-first text for an opportunity.

Plain templates filled from the members' own data. No model is involved, and
nothing here claims more than the data shows.
"""

from __future__ import annotations

from typing import Any

from core.opportunities.actions import REMOVE, RETENTION, REVIEW, RIGHTSIZE, STOP
from core.reports.basis import basis_split_text

_RISK = {
    REMOVE: "Removal cannot be undone; data is lost unless it is saved first.",
    STOP: (
        "A stopped resource still bills for its storage, "
        "and restarting needs a window."
    ),
    RIGHTSIZE: (
        "Resizing usually needs a restart, and memory use is not measured, "
        "so a smaller size can run out of memory."
    ),
    RETENTION: "Shorter retention permanently drops older data.",
    REVIEW: (
        "Argus could not decide from the data. " "Do not act before an owner confirms."
    ),
}

_STEPS = {
    REMOVE: [
        "Confirm nothing still uses it "
        "(DNS, allowlists, scripts, infrastructure code).",
        "Check the owner and tags, and ask the owner if unsure.",
        "Save anything that might matter before removing it.",
        "Remove it in a change window and keep the ticket link.",
    ],
    STOP: [
        "Check for schedules or jobs that expect it to be running.",
        "Ask the owner about the restart procedure.",
        "Stop it in a change window and keep the ticket link.",
    ],
    RIGHTSIZE: [
        "Collect memory and peak CPU over a representative period.",
        "Try one non-critical instance first.",
        "Plan a restart window.",
        "Compare the bill after one full billing cycle.",
    ],
    RETENTION: [
        "Check audit, legal and security retention rules first.",
        "Archive older data if it may be needed.",
        "Set the retention and confirm new data still arrives.",
    ],
    REVIEW: [
        "Ask the resource owner whether it is still used.",
        "Look at recent access in the audit trail.",
        "Extend the metrics window or enable missing metrics.",
        "Decide: keep, remove or resize.",
    ],
}

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def build_guidance(
    action: str,
    members: list[dict[str, Any]],
    confidence: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evidence": _evidence(members, confidence, summary),
        "risk": _risk(action, members, confidence, summary),
        "check_first": _steps(action, members, summary),
    }


def _evidence(
    members: list[dict[str, Any]], confidence: str, summary: dict[str, Any]
) -> list[str]:
    rules = sum(1 for f in members if _by_rule(f))
    model = len(members) - rules
    lines = [f"Found: {rules} by deterministic rules, {model} by model review."]
    reviewed = [f for f in members if not _by_rule(f)]
    if reviewed:
        with_metrics = sum(1 for f in reviewed if _metrics(f).get("metrics"))
        checked = sum(1 for f in reviewed if _metrics(f).get("last_activity_checked"))
        lines.append(
            f"Metrics available for {with_metrics} of {len(reviewed)} "
            "model-reviewed members."
        )
        lines.append(
            f"Last activity checked for {checked} of {len(reviewed)} "
            "model-reviewed members."
        )
    split = basis_split_text(summary)
    if split:
        lines.append(f"Dollars: {split}.")
    lines.append(f"Lowest confidence: {confidence}.")
    return lines


def _risk(
    action: str,
    members: list[dict[str, Any]],
    confidence: str,
    summary: dict[str, Any],
) -> str:
    parts = [_RISK.get(action, _RISK[REVIEW])]
    reasons = sorted({r for f in members for r in (f.get("review_reasons") or [])})
    if reasons:
        parts.append(f"Flagged for human review: {', '.join(reasons)}.")
    if _CONFIDENCE_RANK.get(confidence, 0) == 0:
        parts.append(
            "Low confidence: the evidence behind some findings was missing or short."
        )
    unpriced = summary["unpriced_findings"]
    if unpriced:
        noun = "member has" if unpriced == 1 else "members have"
        parts.append(
            f"{unpriced} {noun} no dollar figure; check the bill before using "
            "the savings range."
        )
    return " ".join(parts)


def _steps(
    action: str, members: list[dict[str, Any]], summary: dict[str, Any]
) -> list[str]:
    types = " ".join(str(f.get("resource_type") or "").lower() for f in members)
    steps: list[str] = []
    if action == REMOVE:
        if "eip" in types or "elastic-ip" in types or "address" in types:
            steps.append(
                "Check partner, broker and firewall allowlists before releasing; "
                "a released address cannot be recovered."
            )
        if "volume" in types:
            steps.append(
                "Take a snapshot first unless one already exists and restores cleanly."
            )
        if "snapshot" in types:
            steps.append(
                "Confirm the source resource is gone or the snapshot is no longer "
                "needed to restore."
            )
    if action in (REMOVE, STOP) and "instance" in types:
        steps.append(
            "Ask the owner why it was stopped and whether it restarts on a schedule."
        )
    steps += _STEPS.get(action, _STEPS[REVIEW])
    if summary["unpriced_findings"]:
        steps.append(
            "Check the bill for the real monthly cost; "
            "some members have no dollar figure."
        )
    return steps


def _by_rule(f: dict[str, Any]) -> bool:
    return str(f.get("detected_by") or "").startswith("rule:")


def _metrics(f: dict[str, Any]) -> dict[str, Any]:
    return f.get("metrics_summary") or {}
