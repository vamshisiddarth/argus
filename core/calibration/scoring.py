"""Score a scan report against the manifest and compare it with a baseline."""

from __future__ import annotations

import statistics
from typing import Any

from core.reports.basis import cost_summary


def score_report(report: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    tag_key = manifest["tag_key"]
    resources = {r["id"]: r for r in manifest["resources"]}
    found: dict[str, dict[str, Any]] = {}
    unlabelled = 0
    for f in report.get("findings") or []:
        rid = (f.get("tags") or {}).get(tag_key)
        if not isinstance(rid, str) or rid not in resources:
            unlabelled += 1
            continue
        best = found.get(rid)
        if best is None or _cost(f) > _cost(best):
            found[rid] = f

    waste = [r for r in resources.values() if r["kind"] == "waste"]
    true_pos = [r["id"] for r in waste if r["id"] in found]
    false_neg = [r["id"] for r in waste if r["id"] not in found]
    false_pos = [
        r["id"] for r in resources.values() if r["kind"] == "decoy" and r["id"] in found
    ]
    flagged = len(true_pos) + len(false_pos)
    return {
        "manifest_version": manifest["version"],
        "schema_version": report.get("schema_version"),
        "recall": (len(true_pos) / len(waste)) if waste else None,
        "precision": (len(true_pos) / flagged) if flagged else None,
        "true_positives": true_pos,
        "false_negatives": false_neg,
        "false_positives": false_pos,
        "unlabelled_findings": unlabelled,
        "findings_total": len(report.get("findings") or []),
        "by_class": _by_class(manifest, waste, found),
        "cost": _cost_block(resources, true_pos, found),
        "evidence_complete_share": _evidence_share(true_pos, found),
        "llm_cost_usd": _llm_cost(report),
    }


def _cost(finding: dict[str, Any]) -> float:
    return float(finding.get("estimated_monthly_cost") or 0.0)


def _by_class(
    manifest: dict[str, Any],
    waste: list[dict[str, Any]],
    found: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, spec in manifest["classes"].items():
        members = [r for r in waste if r["class"] == name]
        hits = sum(1 for r in members if r["id"] in found)
        recall = (hits / len(members)) if members else None
        out[name] = {
            "total": len(members),
            "found": hits,
            "recall": recall,
            "target": spec["target_recall"],
            "target_met": None if recall is None else recall >= spec["target_recall"],
        }
    return out


def _cost_block(
    resources: dict[str, dict[str, Any]],
    true_pos: list[str],
    found: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    errors: dict[str, float] = {}
    unpriced = 0
    for rid in true_pos:
        expected = resources[rid].get("expected_monthly_usd")
        estimate = _cost(found[rid])
        if estimate <= 0:
            unpriced += 1
        elif expected:
            errors[rid] = round(abs(estimate - expected) / expected, 4)
    values = list(errors.values())
    summary = cost_summary([found[rid] for rid in true_pos])
    return {
        "errors": errors,
        "mean_error": round(statistics.fmean(values), 4) if values else None,
        "median_error": round(statistics.median(values), 4) if values else None,
        "max_error": max(values) if values else None,
        "unpriced_true_positives": unpriced,
        "verified_share": summary["verified_share"],
    }


def _evidence_share(
    true_pos: list[str], found: dict[str, dict[str, Any]]
) -> float | None:
    if not true_pos:
        return None
    complete = 0
    for rid in true_pos:
        f = found[rid]
        by_rule = str(f.get("detected_by") or "").startswith("rule:")
        metrics = (f.get("metrics_summary") or {}).get("metrics")
        if by_rule or metrics:
            complete += 1
    return complete / len(true_pos)


def _llm_cost(report: dict[str, Any]) -> float | None:
    spent = (report.get("scan_window") or {}).get("llm_spent_usd")
    if spent is not None:
        return float(spent)
    estimated = report.get("estimated_agent_cost_usd")
    return None if estimated is None else float(estimated)


def compare_to_baseline(
    current: dict[str, Any], baseline: dict[str, Any], tolerance: float = 0.05
) -> list[str]:
    """Plain-language regressions of current against baseline; empty when none."""
    problems: list[str] = []
    eps = 1e-9

    def dropped(name: str, now: float | None, was: float | None) -> None:
        if was is not None and (now is None or now < was - eps):
            shown = "none" if now is None else f"{now:.2f}"
            problems.append(f"{name} dropped from {was:.2f} to {shown}")

    dropped("recall", current["recall"], baseline["recall"])
    dropped("precision", current["precision"], baseline["precision"])
    for name, was in baseline["by_class"].items():
        now = current["by_class"].get(name, {})
        dropped(f"recall for {name}", now.get("recall"), was.get("recall"))
    dropped(
        "verified share",
        current["cost"]["verified_share"],
        baseline["cost"]["verified_share"],
    )
    was_err = baseline["cost"]["mean_error"]
    now_err = current["cost"]["mean_error"]
    if was_err is not None and now_err is not None and now_err > was_err + tolerance:
        problems.append(f"mean cost error rose from {was_err:.2f} to {now_err:.2f}")
    return problems


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def render_markdown(score: dict[str, Any]) -> str:
    cost = score["cost"]
    lines = [
        "# Argus testbed scorecard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Recall | {_pct(score['recall'])} |",
        f"| Precision | {_pct(score['precision'])} |",
        f"| Mean cost error | {_pct(cost['mean_error'])} |",
        f"| Max cost error | {_pct(cost['max_error'])} |",
        f"| Unpriced true positives | {cost['unpriced_true_positives']} |",
        f"| Verified share of true-positive dollars | {_pct(cost['verified_share'])} |",
        f"| Evidence complete | {_pct(score['evidence_complete_share'])} |",
        f"| Findings (total / outside the testbed) | "
        f"{score['findings_total']} / {score['unlabelled_findings']} |",
        f"| LLM cost (USD) | {score['llm_cost_usd']} |",
        "",
        "## By class",
        "",
        "| Class | Found | Recall | Target | Met |",
        "|-------|-------|--------|--------|-----|",
    ]
    for name, c in score["by_class"].items():
        met = "n/a" if c["target_met"] is None else ("yes" if c["target_met"] else "no")
        lines.append(
            f"| {name} | {c['found']}/{c['total']} | {_pct(c['recall'])} "
            f"| {_pct(c['target'])} | {met} |"
        )
    lines += [
        "",
        f"Missed waste: {', '.join(score['false_negatives']) or 'none'}",
        f"Flagged decoys: {', '.join(score['false_positives']) or 'none'}",
        "",
    ]
    return "\n".join(lines)
