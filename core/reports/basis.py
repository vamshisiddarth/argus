"""
Where a finding's dollar figure comes from, and how totals are labelled.

An estimate must never be summed into a verified total without saying so.
"""

from __future__ import annotations

from typing import Any

BILLED = "billed"
LIST_PRICE = "list_price"
MODEL_ESTIMATE = "model_estimate"
UNKNOWN = "unknown"
BASES = (BILLED, LIST_PRICE, MODEL_ESTIMATE, UNKNOWN)

# Provisional, not measured: a total is called "estimated" rather than
# "unverified" once at least this share of its dollars is billed.
HEADLINE_VERIFIED_SHARE = 0.5

_LABELS = {
    BILLED: "billed",
    LIST_PRICE: "list price",
    MODEL_ESTIMATE: "model estimate",
}


def normalize_basis(basis: str | None, cost: float | None) -> str:
    """Map any stored value (including legacy ones) onto the four known bases."""
    amount = float(cost or 0.0)
    if amount <= 0:
        return UNKNOWN
    if basis in (BILLED, LIST_PRICE, MODEL_ESTIMATE):
        return basis
    return MODEL_ESTIMATE


def cost_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Dollars and counts per basis, the billed share, and the headline verdict."""
    usd = {b: 0.0 for b in BASES}
    count = {b: 0 for b in BASES}
    for f in findings:
        cost = float(f.get("estimated_monthly_cost") or 0.0)
        basis = normalize_basis(f.get("cost_basis"), cost)
        usd[basis] += cost
        count[basis] += 1
    total = sum(usd.values())
    verified = usd[BILLED]
    share = round(verified / total, 4) if total > 0 else None
    return {
        "waste_by_basis": {b: round(v, 2) for b, v in usd.items()},
        "findings_by_basis": count,
        "unpriced_findings": count[UNKNOWN],
        "verified_waste_usd": round(verified, 2),
        "verified_share": share,
        "headline_is_verified": share is None or share >= HEADLINE_VERIFIED_SHARE,
    }


def basis_split_text(summary: dict[str, Any]) -> str:
    """'$10.00 billed, $4.00 list price, $86.00 model estimate, 2 unpriced'."""
    parts = [
        f"${summary['waste_by_basis'][b]:,.2f} {_LABELS[b]}"
        for b in (BILLED, LIST_PRICE, MODEL_ESTIMATE)
        if summary["waste_by_basis"].get(b)
    ]
    if summary.get("unpriced_findings"):
        parts.append(f"{summary['unpriced_findings']} unpriced")
    return ", ".join(parts)


def headline_noun(report: dict[str, Any]) -> str:
    """The words that go after a headline dollar figure."""
    summary = report.get("cost_summary") or cost_summary(report.get("findings") or [])
    share = summary["verified_share"]
    if share is not None and share >= 1.0:
        return "billed waste"
    if summary["headline_is_verified"]:
        return "estimated waste"
    return "unverified waste estimate"
