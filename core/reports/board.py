"""
Static board report: the grouped opportunities as one self-contained HTML page.

No server, no network. The page carries its own CSS and JavaScript, allowed by
hash in a Content Security Policy; every string from the scan is escaped.
Decisions (approve, investigate, keep) live in the browser and can be exported.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from typing import Any
from urllib.parse import quote

from core.opportunities import build_opportunity_block
from core.reports.basis import cost_summary, headline_noun
from core.reports.board_assets import CSS, LOGIC_JS, LOGO_INNER, LOGO_SVG, UI_JS
from core.reports.generator import review_summary

MAX_MEMBER_ROWS = 300

_BASIS = {
    "billed": ("chip-billed", "billed", "Billed: taken from the cloud bill."),
    "list_price": (
        "chip-list",
        "list price",
        "List price: priced from the public list price, not billed.",
    ),
    "model_estimate": (
        "chip-model",
        "model est.",
        "Model estimate: the AI's guess, not billed.",
    ),
    "unknown": (
        "chip-unpriced",
        "unpriced",
        "Unpriced: no dollar figure could be established.",
    ),
}
_ACTION_LABEL = {
    "remove": "Remove",
    "stop": "Stop",
    "rightsize": "Right-size",
    "retention": "Set retention",
    "review": "Review",
}
_TIER_LABEL = {
    "sure": "confident",
    "unsure": "low confidence",
    "flagged": "needs human review",
}


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _usd(value: float) -> str:
    if value == 0:
        return "$0"
    return f"${value:,.0f}" if abs(value) >= 100 else f"${value:,.2f}"


def _chip(kind: str, text: str | None = None) -> str:
    css, label, title = _BASIS[kind]
    return f'<span class="bchip {css}" title="{_e(title)}">{_e(text or label)}</span>'


def _with_opportunities(report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict]:
    opps = report.get("opportunities")
    if opps and all("check_first" in o for o in opps):
        return opps, report.get("opportunity_summary") or {}
    return build_opportunity_block(report.get("findings") or [])


def _basis_chips(savings: dict[str, Any]) -> str:
    out = []
    for kind in ("billed", "list_price", "model_estimate"):
        amount = savings["by_basis"].get(kind, 0)
        if amount:
            out.append(_chip(kind, f"{_BASIS[kind][1]} {_usd(amount)}"))
    if savings.get("unpriced"):
        out.append(_chip("unknown", f"{savings['unpriced']} unpriced"))
    return "".join(out)


def _range_text(savings: dict[str, Any]) -> str:
    low, high = savings["low_usd"], savings["high_usd"]
    if round(low) == round(high):
        return _usd(high)
    return f"{_usd(low)} to {_usd(high)}"


def _members_table(
    opp: dict[str, Any], by_id: dict[str, dict[str, Any]], idx: int
) -> str:
    rows = []
    for rid in opp["members"][:MAX_MEMBER_ROWS]:
        f = by_id.get(rid, {"resource_id": rid})
        cost = float(f.get("estimated_monthly_cost") or 0.0)
        basis = f.get("cost_basis") if cost > 0 else "unknown"
        kind = basis if basis in _BASIS else "model_estimate"
        amount = _usd(cost) if cost > 0 else "-"
        flag = (
            '<span class="pill pill-bad">review</span>'
            if f.get("review_required")
            else ""
        )
        label = f.get("name") or rid
        sub = f'<br><span class="muted mono">{_e(rid)}</span>' if f.get("name") else ""
        rows.append(
            "<tr>"
            f"<td>{_e(label)}{sub}</td>"
            f"<td>{_e(f.get('resource_type') or '')}</td>"
            f"<td>{_e(f.get('region') or '')}</td>"
            f"<td>{_e(f.get('account_id') or '')}</td>"
            f'<td class="n">{amount} {_chip(kind)}</td>'
            f"<td>{_e(f.get('confidence') or '')}</td>"
            f"<td>{flag}</td>"
            "</tr>"
        )
    more = len(opp["members"]) - MAX_MEMBER_ROWS
    note = (
        f'<p class="muted">{more} more members are listed in the JSON report.</p>'
        if more > 0
        else ""
    )
    return (
        '<div class="tablewrap"><table>'
        f'<caption class="sr">Members of {_e(opp["title"])}</caption>'
        "<thead><tr>"
        '<th scope="col">Resource</th><th scope="col">Type</th>'
        '<th scope="col">Region</th><th scope="col">Account</th>'
        '<th scope="col" class="n">Monthly</th><th scope="col">Confidence</th>'
        '<th scope="col">Flag</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>" + note
    )


def _card(
    opp: dict[str, Any],
    idx: int,
    by_id: dict[str, dict[str, Any]],
    titles: dict[str, str],
) -> str:
    owners = "".join(
        f'<span class="pill pill-flat">{_e(o["tag"])}={_e(o["value"])} ({o["count"]})</span>'
        for o in opp["owners"]
    )
    if opp["unowned_count"]:
        owners += (
            f'<span class="pill pill-flat">no owner tag ({opp["unowned_count"]})</span>'
        )
    related = "".join(
        f'<a class="jump" href="#{_e(r)}">{_e(titles[r])}</a> '
        for r in opp["related"]
        if r in titles
    )
    related_html = f'<p class="jump">Related: {related}</p>' if related else ""
    lane_pill = (
        '<span class="pill pill-easy">Easy</span>'
        if opp["lane"] == "easy"
        else '<span class="pill pill-doubt">Needs an owner</span>'
    )
    tier = opp["key"]["tier"]
    tier_pill = (
        f'<span class="pill {"pill-bad" if tier == "flagged" else "pill-flat"}">'
        f"{_e(_TIER_LABEL[tier])}</span>"
    )
    evidence = "".join(f"<li>{_e(line)}</li>" for line in opp["evidence"])
    steps = "".join(f"<li>{_e(line)}</li>" for line in opp["check_first"])
    cid = f"c{idx}"
    return f"""<article class="card" id="{_e(opp["id"])}" data-id="{_e(opp["id"])}" data-lane="{_e(opp["lane"])}" data-action="{_e(opp["action"])}">
<div class="stripe"></div>
<div class="body">
<div class="card-top">
<h3>{_e(opp["title"])}</h3>
<div class="range mono">{_e(_range_text(opp["savings"]))} <small>a month</small></div>
</div>
<div class="row">{_basis_chips(opp["savings"])}</div>
<div class="row">{lane_pill}<span class="pill pill-flat">{_e(_ACTION_LABEL.get(opp["action"], opp["action"]))}</span>{tier_pill}<span class="pill pill-flat">{opp["member_count"]} members</span><span class="pill pill-flat">priority {_e(opp["priority"])}</span></div>
<p class="risk"><b>Risk.</b> {_e(opp["risk"])}</p>
<details class="more"><summary>Evidence and what to check first</summary>
<h4>Evidence</h4><ul>{evidence}</ul>
<h4>Check first</h4><ol>{steps}</ol>
</details>
<details class="more"><summary>Members ({opp["member_count"]})</summary>
{_members_table(opp, by_id, idx)}
</details>
<div class="row">{owners}</div>
{related_html}
<div class="decide">
<div class="seg" role="group" aria-label="Decision for {_e(opp["title"])}">
<button type="button" data-v="approve" aria-pressed="false">Approve</button>
<button type="button" data-v="investigate" aria-pressed="false">Investigate</button>
<button type="button" data-v="keep" aria-pressed="false">Keep</button>
</div>
<div class="fields">
<div><label for="{cid}-owner">Owner</label><input id="{cid}-owner" class="f-owner" type="text" maxlength="200" autocomplete="off"></div>
<div><label for="{cid}-note">Note</label><input id="{cid}-note" class="f-note" type="text" maxlength="1000" autocomplete="off"></div>
<div><label for="{cid}-expires" class="f-expires-l" hidden>Keep until</label><input id="{cid}-expires" class="f-expires" type="date" hidden></div>
</div>
<p class="hint" hidden></p>
</div>
</div>
</article>"""


def _run_cost(report: dict, summary: dict) -> dict[str, Any]:
    """What this scan cost to run, from the figures the report records."""
    win = report.get("scan_window") or {}
    spend = win.get("llm_spent_usd")
    if spend is None:
        spend = report.get("estimated_agent_cost_usd")
    cov = report.get("coverage") or {}
    by_basis = summary["waste_by_basis"]
    return {
        "spend": None if spend is None else float(spend),
        "budget": win.get("llm_budget_usd"),
        "estimate": win.get("llm_estimate_usd"),
        "calls": (win.get("llm_calibration") or {}).get("calls"),
        "tokens_in": report.get("agent_input_tokens"),
        "tokens_out": report.get("agent_output_tokens"),
        "analysed": cov.get("analysed"),
        "deterministic_waste": by_basis["billed"] + by_basis["list_price"],
    }


def _run_cost_bar(spend: float, budget: float) -> str:
    pct = spend / budget * 100
    width = min(pct, 100)
    css = "b-over" if pct > 100 else "b-run"
    label = f"Model spend {_usd(spend)} is {pct:.0f}% of the {_usd(budget)} budget"
    return (
        '<svg class="bar" viewBox="0 0 100 4" preserveAspectRatio="none" role="img" '
        f'aria-label="{_e(label)}"><rect class="{css}" x="0" y="0" '
        f'width="{width:.2f}" height="4"/></svg>'
    )


def _run_cost_panel(rc: dict[str, Any]) -> str:
    spend = rc["spend"]
    if spend is None:
        body = '<p class="muted">Model spend: not recorded in this report.</p>'
        return f'<div class="panel"><h3>Cost of this run</h3>{body}</div>'
    lines = []
    bar = ""
    if rc["budget"]:
        pct = spend / rc["budget"] * 100
        bar = _run_cost_bar(spend, rc["budget"])
        over = " Over budget." if pct > 100 else ""
        lines.append(f"{pct:.0f}% of the {_usd(rc['budget'])} budget.{over}")
    if rc["estimate"]:
        diff = (spend - rc["estimate"]) / rc["estimate"] * 100
        word = (
            "matches"
            if round(diff) == 0
            else (f"{abs(diff):.0f}% {'higher' if diff > 0 else 'lower'}")
        )
        lines.append(
            f"Estimated before the run: {_usd(rc['estimate'])} (actual {word})."
        )
    parts = []
    if rc["calls"]:
        parts.append(f"{rc['calls']} model calls")
    if rc["tokens_in"] is not None and rc["tokens_out"] is not None:
        parts.append(
            f"{rc['tokens_in']:,} input and {rc['tokens_out']:,} output tokens"
        )
    if parts:
        lines.append(", ".join(parts) + ".")
    if rc["analysed"] and spend > 0:
        lines.append(
            f"{_usd(spend / rc['analysed'] * 1000)} per 1,000 resources analysed "
            f"({rc['analysed']:,})."
        )
    if spend > 0 and rc["deterministic_waste"] > 0:
        lines.append(
            f"{_usd(round(rc['deterministic_waste'] / spend))} of billed or "
            "list-priced waste found per $1 of model spend. This is waste found, "
            "not savings realized."
        )
    lines.append(
        "Not included: AWS API charges (for example Cost Explorer requests) and "
        "the cost of the place Argus runs."
    )
    items = "".join(f"<li>{_e(line)}</li>" for line in lines)
    return (
        '<div class="panel"><h3>Cost of this run</h3>'
        f'<p class="mono big">{_usd(spend)} <small>model spend</small></p>'
        f"{bar}<ul>{items}</ul></div>"
    )


def _kpis(report: dict, summary: dict, opp_stats: dict, noun: str) -> str:
    findings = report.get("findings") or []
    total = sum(float(f.get("estimated_monthly_cost") or 0.0) for f in findings)
    share = summary["verified_share"]
    cov = report.get("coverage") or {}
    review_n, review_usd = review_summary(findings)
    note = "All of it is billed." if share == 1.0 else "Estimate only, not billed."
    if review_n:
        note += f" {_usd(review_usd)} in {review_n} findings need human review."
    cards = [
        (
            "kpi",
            noun,
            f"{_usd(total)}<small> a month</small>",
            _e(note),
        ),
        (
            "kpi",
            "Opportunities",
            str(opp_stats.get("opportunities", 0)),
            f"from {len(findings)} findings"
            + (
                f" ({opp_stats['reduction_ratio']}x fewer)"
                if opp_stats.get("reduction_ratio")
                else ""
            ),
        ),
        (
            "kpi" + (" alert" if share is not None and share < 0.5 else ""),
            "Billed share",
            "n/a" if share is None else f"{round(share * 100)}%",
            "of the reported dollars come from the bill",
        ),
        (
            "kpi" + (" alert" if summary["unpriced_findings"] else ""),
            "Unpriced findings",
            str(summary["unpriced_findings"]),
            "no dollar figure; not in the range",
        ),
    ]
    if cov:
        cards.append(
            (
                "kpi",
                "Resources analysed",
                f"{cov.get('analysed', 0):,} of {cov.get('discovered', 0):,}",
                f"{cov.get('dropped', 0)} dropped, "
                f"{cov.get('free_config_skipped', 0)} free config objects skipped",
            )
        )
    rc = _run_cost(report, summary)
    if rc["spend"] is None:
        cards.append(("kpi", "Cost of this run", "n/a", "not recorded in this report"))
    else:
        sub = []
        if rc["budget"]:
            sub.append(f"of {_usd(rc['budget'])} budget")
        if rc["calls"]:
            sub.append(f"{rc['calls']} model calls")
        cards.append(
            (
                "kpi",
                "Cost of this run",
                _usd(rc["spend"]),
                ", ".join(sub) or "model spend",
            )
        )
    return "".join(
        f'<div class="{cls}"><span class="eyebrow">{_e(label)}</span>'
        f'<span class="v">{value}</span><span class="s">{sub}</span></div>'
        for cls, label, value, sub in cards
    )


def _bar(summary: dict) -> str:
    usd = summary["waste_by_basis"]
    total = sum(usd[k] for k in ("billed", "list_price", "model_estimate"))
    if total <= 0:
        return '<p class="muted">No priced dollars to show.</p>'
    x = 0.0
    rects = []
    for key, css in (
        ("billed", "b-billed"),
        ("list_price", "b-list"),
        ("model_estimate", "b-model"),
    ):
        w = usd[key] / total * 100
        if w > 0:
            rects.append(
                f'<rect class="{css}" x="{x:.2f}" y="0" width="{w:.2f}" height="4"/>'
            )
            x += w
    label = "; ".join(
        f"{_BASIS[k][1]} {_usd(usd[k])}"
        for k in ("billed", "list_price", "model_estimate")
        if usd[k]
    )
    legend = "".join(
        f'<li><span class="sw {sw}"></span>{_e(_BASIS[k][1])} <span class="mono">{_usd(usd[k])}</span> '
        f"({usd[k] / total * 100:.0f}%)</li>"
        for k, sw in (
            ("billed", "sw-billed"),
            ("list_price", "sw-list"),
            ("model_estimate", "sw-model"),
        )
        if usd[k]
    )
    return (
        f'<svg class="bar" viewBox="0 0 100 4" preserveAspectRatio="none" role="img" '
        f'aria-label="Dollars by cost basis: {_e(label)}">{"".join(rects)}</svg>'
        f'<ul class="legend">{legend}</ul>'
    )


def _lanes_panel(opps: list[dict[str, Any]]) -> str:
    rows = []
    for lane, label, note in (
        ("easy", "Easy", "clear evidence, confident, no review flag"),
        ("doubt", "Needs an owner", "uncertain, flagged or a judgement call"),
    ):
        group = [o for o in opps if o["lane"] == lane]
        members = sum(o["member_count"] for o in group)
        low = sum(o["savings"]["low_usd"] for o in group)
        high = sum(o["savings"]["high_usd"] for o in group)
        rows.append(
            f'<div class="lane-row"><div><b>{label}</b><br><span class="muted">{note}</span></div>'
            f'<div class="mono">{len(group)} opportunities<br>{members} members<br>'
            f"{_usd(low)} to {_usd(high)}</div></div>"
        )
    return "".join(rows)


def _preflight_lines(report: dict) -> list[str]:
    pre = report.get("preflight") or {}
    lines = []
    if pre.get("skipped"):
        lines.append("Pre-scan checks were skipped; the environment was not verified.")
    accounts = pre.get("accounts") or []
    for acct in accounts:
        for check in acct.get("checks") or []:
            status = check.get("status")
            if status not in ("warn", "fail"):
                continue
            text = f"{check.get('code', '')}: {check.get('message', '')}"
            if status == "fail":
                text = f"FAILED {text}"
            if len(accounts) > 1:
                text = f"{acct.get('account_id', '')}: {text}"
            lines.append(text)
    return lines


def _warnings_banner(report: dict) -> str:
    errors = [
        f"{e.get('account_id', '')}: {e.get('error', '')}"
        for e in report.get("scan_errors") or []
    ]
    items = "".join(f"<li>{_e(w)}</li>" for w in _preflight_lines(report) + errors)
    if not items:
        return ""
    return (
        '<div class="banner" role="note"><b>Read before deciding.</b>'
        f"<ul>{items}</ul></div>"
    )


def _about(report: dict) -> str:
    cov = report.get("coverage") or {}
    win = report.get("scan_window") or {}
    coverage = (
        f"Analysed {_e(cov.get('analysed'))} of {_e(cov.get('discovered'))} resources, "
        f"{_e(cov.get('dropped', 0))} dropped, {_e(cov.get('free_config_skipped', 0))} "
        f"free configuration objects skipped, {len(cov.get('regions_covered') or [])} regions."
        if cov
        else "This report carries no coverage block."
    )
    window = (
        f" Metrics window {_e(win['metrics_lookback_days'])} days."
        if win.get("metrics_lookback_days")
        else ""
    )
    return f"""<details class="about"><summary>About this report</summary>
<ul>
<li>Scan {_e(report.get("scan_id", ""))}, generated {_e(report.get("generated_at", ""))}, schema {_e(report.get("schema_version", "unknown"))}.</li>
<li>{coverage}{window}</li>
<li><b>Opportunity</b>: findings that call for the same action on the same kind of resource, grouped without a model. <b>Easy</b> means removal, stop or retention with confident findings and no review flag; everything else needs an owner.</li>
<li><b>Range</b>: the low end is billed plus list-priced dollars, the high end adds the model's estimates, unpriced members are in neither. <b>Billed</b> is verified, <b>list price</b> is deterministic but not billed, <b>model est.</b> is a guess.</li>
<li>An opportunity keeps its id from scan to scan, so exported decisions still match a later report.</li>
<li>Nothing is sent anywhere: decisions stay in this browser or in the file you export. Argus never changes a resource, and commitments (Savings Plans, reservations) are not analysed in this version.</li>
</ul></details>"""


def _data_block(report: dict, opps: list[dict[str, Any]]) -> str:
    rows = []
    for o in opps:
        search = " ".join(
            [o["title"], o["action"], o["lane"], *o["resource_types"], *o["accounts"]]
            + [f"{x['tag']}={x['value']}" for x in o["owners"]]
        ).lower()
        rows.append(
            {
                "id": o["id"],
                "title": o["title"],
                "lane": o["lane"],
                "action": o["action"],
                "tier": o["key"]["tier"],
                "low": o["savings"]["low_usd"],
                "high": o["savings"]["high_usd"],
                "unpriced": o["savings"]["unpriced"],
                "members": o["member_count"],
                "search": search,
            }
        )
    data = {
        "scan_id": str(report.get("scan_id") or "unknown"),
        "generated_at": str(report.get("generated_at") or ""),
        "cloud": str(report.get("cloud") or ""),
        "total_low": round(sum(r["low"] for r in rows), 2),
        "total_high": round(sum(r["high"] for r in rows), 2),
        "opportunities": rows,
    }
    text = json.dumps(data, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _favicon() -> str:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">{LOGO_INNER}</svg>'
    return "data:image/svg+xml," + quote(svg, safe="")


def _sri(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


def build_board_html(report: dict[str, Any]) -> str:
    opps, opp_stats = _with_opportunities(report)
    findings = report.get("findings") or []
    by_id = {str(f.get("resource_id")): f for f in findings}
    summary = report.get("cost_summary") or cost_summary(findings)
    noun = headline_noun({**report, "cost_summary": summary})
    titles = {o["id"]: o["title"] for o in opps}
    cloud = str(report.get("cloud") or "cloud").upper()
    date = str(report.get("generated_at") or "")[:10]
    accounts = len(report.get("accounts_scanned") or [])

    script = LOGIC_JS + UI_JS
    csp = (
        "default-src 'none'; "
        f"style-src '{_sri(CSS)}'; script-src '{_sri(script)}'; "
        "img-src data:; base-uri 'none'; form-action 'none'"
    )

    cards = "".join(_card(o, i, by_id, titles) for i, o in enumerate(opps))
    if not opps:
        cards = (
            '<p class="empty">No wasteful resources were identified in this scan.</p>'
        )
    actions = sorted({o["action"] for o in opps})
    action_options = "".join(
        f'<option value="{_e(a)}">{_e(_ACTION_LABEL.get(a, a))}</option>'
        for a in actions
    )

    page = f"""<!doctype html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="referrer" content="no-referrer">
<link rel="icon" href="{_favicon()}">
<title>Argus board - {_e(cloud)} - {_e(date)}</title>
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#board">Skip to the decision board</a>
<header class="topbar">
<div class="brand">{LOGO_SVG}<span class="logo">Argus</span></div>
<h1>Spend decision board</h1>
<p class="meta">{_e(cloud)} - scanned {_e(date)} - {accounts} account{"s" if accounts != 1 else ""} - {len(findings)} findings in {len(opps)} opportunities</p>
<button type="button" id="theme" class="btn">Switch theme</button>
</header>
<div class="tally" id="tally" role="region" aria-label="Decision tally">
<div class="totals" aria-live="polite">
<div class="t"><span class="eyebrow">Approved a month</span><span class="v pos" id="t-approved">$0</span><span class="s" id="t-approved-s">Nothing approved yet</span></div>
<div class="t"><span class="eyebrow">Investigating</span><span class="v warn" id="t-investigating">$0</span><span class="s" id="t-investigating-s">0 under investigation</span></div>
<div class="t"><span class="eyebrow">Kept</span><span class="v" id="t-kept">0</span><span class="s" id="t-kept-s">Kept on purpose</span></div>
<div class="t"><span class="eyebrow">Undecided</span><span class="v" id="t-undecided">{len(opps)}</span><span class="s" id="t-undecided-s">of {len(opps)} opportunities</span></div>
</div>
<div class="tools">
<button type="button" id="export-json" class="btn">Export decisions</button>
<button type="button" id="export-csv" class="btn">Export CSV</button>
<label for="import-file" class="btn">Import decisions</label>
<input id="import-file" class="sr" type="file" accept="application/json,.json">
<button type="button" id="clear-all" class="btn">Clear all</button>
</div>
</div>
<p id="status" class="sr" aria-live="polite"></p>
<noscript><p class="empty">Decisions, filters and exports need JavaScript. The opportunities below are complete without it.</p></noscript>
<main>
<section id="overview" aria-labelledby="h-overview">
<h2 id="h-overview"><span class="num">01</span> Overview</h2>
{_warnings_banner(report)}
<div class="kpis">{_kpis(report, summary, opp_stats, noun)}</div>
<div class="panels">
<div class="panel"><h3>Where the money is</h3>{_bar(summary)}<hr>{_lanes_panel(opps)}</div>
{_run_cost_panel(_run_cost(report, summary))}
</div>
</section>
<section id="board" aria-labelledby="h-board">
<h2 id="h-board"><span class="num">02</span> Decide</h2>
<div class="dashboard">
<aside class="rail" aria-label="Filters">
<h3>Filter</h3>
<div class="chips" role="group" aria-label="Show">
<button type="button" class="fchip" data-chip="all" aria-pressed="true">All</button>
<button type="button" class="fchip" data-chip="easy" aria-pressed="false">Easy</button>
<button type="button" class="fchip" data-chip="doubt" aria-pressed="false">Needs an owner</button>
<button type="button" class="fchip" data-chip="undecided" aria-pressed="false">Undecided</button>
<button type="button" class="fchip" data-chip="approve" aria-pressed="false">Approved</button>
<button type="button" class="fchip" data-chip="investigate" aria-pressed="false">Investigating</button>
<button type="button" class="fchip" data-chip="keep" aria-pressed="false">Kept</button>
</div>
<div><label for="f-action">Action</label><select id="f-action"><option value="all">All actions</option>{action_options}</select></div>
<div><label for="f-search">Search</label><input id="f-search" type="search" autocomplete="off"></div>
<p id="count" class="muted" aria-live="polite">Showing {len(opps)} of {len(opps)} opportunities</p>
<button type="button" id="reset-filters" class="btn">Reset filters</button>
</aside>
<div class="content">
<div class="cards" id="cards">{cards}</div>
<p id="no-match" class="empty" hidden>No opportunity matches these filters.</p>
</div>
</div>
</section>
<section id="keep" aria-labelledby="h-keep">
<h2 id="h-keep"><span class="num">03</span> Kept on purpose</h2>
<div class="panels"><div class="panel"><ul id="keep-list"></ul><p id="keep-empty" class="muted">Nothing is marked Keep.</p></div></div>
</section>
</main>
<footer class="foot">
{_about(report)}
<p>Generated by Argus. This page makes no network requests.</p>
</footer>
<script type="application/json" id="board-data">{_data_block(report, opps)}</script>
<script>{script}</script>
</body>
</html>
"""
    return page.encode("ascii", "xmlcharrefreplace").decode("ascii")
