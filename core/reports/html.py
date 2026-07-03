"""
Self-contained HTML report generator for Argus.

Produces a single HTML file with:
- Summary stats header
- AI executive summary
- Filterable/sortable findings table
- Expandable rows with AI reasoning and recommendation

The output is intentionally self-contained (no external CDN) so it works
offline and is safe to serve from a pre-signed S3 URL.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from core.registry import get_registry


def build_html_report(report: dict[str, Any]) -> str:
    cloud = report["cloud"].upper()
    total = report["total_estimated_waste_usd"]
    count = report["findings_count"]
    generated_at = report["generated_at"][:10]
    scan_id = report["scan_id"]
    accounts = ", ".join(report.get("accounts_scanned", [])) or "—"
    summary = html.escape(report.get("executive_summary", ""))
    findings = report["findings"]
    scan_errors = report.get("scan_errors") or []

    rows_html = _build_rows(findings)
    errors_html = _build_errors_banner(
        scan_errors, len(report.get("accounts_scanned", []))
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Argus — {cloud} Waste Report ({generated_at})</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:14px;line-height:1.5;color:#111;background:#f5f5f4}}
a{{color:#185fa5;text-decoration:none}}
a:hover{{text-decoration:underline}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 16px}}
.header{{background:#fff;border:1px solid #e5e5e5;border-radius:10px;padding:20px 24px;margin-bottom:16px}}
.header-top{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
.logo{{width:22px;height:22px}}
.title{{font-size:17px;font-weight:600}}
.meta{{font-size:12px;color:#888;margin-left:auto}}
.stats{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px}}
.stat{{background:#f5f5f4;border-radius:8px;padding:10px 16px;min-width:120px}}
.stat-val{{font-size:22px;font-weight:600}}
.stat-val.red{{color:#a32d2d}}
.stat-lbl{{font-size:11px;color:#666;margin-top:2px}}
.summary{{font-size:13px;color:#444;line-height:1.7;border-left:3px solid #e5e5e5;padding-left:12px}}
.error-banner{{background:#fff8e1;border:1px solid #f59e0b;border-radius:10px;padding:14px 18px;margin-bottom:16px}}
.error-banner-title{{font-size:13px;font-weight:600;color:#92400e;margin-bottom:6px}}
.error-banner ul{{margin:0;padding-left:18px;font-size:12px;color:#92400e;line-height:1.8}}
.error-banner code{{background:#fef3c7;border-radius:3px;padding:1px 4px;font-family:'SFMono-Regular',Consolas,monospace}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}}
.filters select,.filters input{{background:#fff;border:1px solid #d4d4d4;border-radius:6px;padding:6px 10px;font-size:13px;color:#111;outline:none}}
.filters select:focus,.filters input:focus{{border-color:#378add}}
.count-label{{margin-left:auto;font-size:12px;color:#888}}
.card{{background:#fff;border:1px solid #e5e5e5;border-radius:10px;overflow:hidden}}
table{{width:100%;border-collapse:collapse}}
thead th{{font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.04em;padding:9px 12px;border-bottom:1px solid #e5e5e5;background:#fafaf9;text-align:left;white-space:nowrap}}
thead th.sort{{cursor:pointer;user-select:none}}
thead th.sort:hover{{color:#111}}
tbody tr{{transition:background .1s}}
tbody tr:hover{{background:#fafaf9}}
tbody td{{padding:10px 12px;border-bottom:1px solid #f0f0f0;vertical-align:middle}}
tbody tr:last-child td{{border-bottom:none}}
.expand-btn{{background:none;border:none;cursor:pointer;color:#888;font-size:16px;line-height:1;padding:2px 4px;border-radius:4px}}
.expand-btn:hover{{background:#f0f0f0;color:#111}}
.pill{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
.pill-high{{background:#fcebeb;color:#a32d2d}}
.pill-medium{{background:#faeeda;color:#854f0b}}
.pill-low{{background:#eaf3de;color:#3b6d11}}
.mono{{font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;font-size:12px}}
.muted{{color:#888}}
.cost-high{{font-weight:600;color:#a32d2d}}
.cost-medium{{font-weight:600;color:#854f0b}}
.cost-low{{font-weight:600;color:#3b6d11}}
.detail-row td{{padding:0}}
.detail-inner{{display:none;background:#fafaf9;border-top:1px solid #f0f0f0;padding:12px 16px;font-size:12px;line-height:1.7;color:#444}}
.detail-inner.open{{display:block}}
.detail-label{{font-weight:600;color:#111;margin-right:4px}}
.footer{{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-top:1px solid #f0f0f0;font-size:11px;color:#aaa}}
@media(max-width:640px){{.stats{{flex-direction:column}}.meta{{display:none}}}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="header-top">
      <svg class="logo" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M12 4L4 8l8 4 8-4-8-4z" fill="#E24B4A"/>
        <path d="M4 12l8 4 8-4M4 16l8 4 8-4" stroke="#E24B4A" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
      <span class="title">Argus — {cloud} Waste Report</span>
      <span class="meta">{generated_at} &nbsp;·&nbsp; Scan {scan_id[:8]} &nbsp;·&nbsp; Accounts: {html.escape(accounts)}</span>
    </div>
    <div class="stats">
      <div class="stat"><div class="stat-val red">${total:,.2f}</div><div class="stat-lbl">estimated waste / month</div></div>
      <div class="stat"><div class="stat-val">{count}</div><div class="stat-lbl">findings</div></div>
      <div class="stat"><div class="stat-val">{len(report.get("accounts_scanned", []))}</div><div class="stat-lbl">accounts scanned</div></div>
    </div>
    <p class="summary">{summary}</p>
  </div>
{errors_html}
  <div class="filters">
    <select id="f-priority" onchange="applyFilters()">
      <option value="">All priorities</option>
      <option>high</option><option>medium</option><option>low</option>
    </select>
    <select id="f-type" onchange="applyFilters()">
      <option value="">All types</option>
      {_build_type_options(findings)}
    </select>
    <input id="f-search" placeholder="Search resource ID, name, or region…" oninput="applyFilters()" style="min-width:220px">
    <span class="count-label" id="count-label">Showing {count} of {count} findings</span>
  </div>

  <div class="card">
    <table id="findings-table">
      <thead>
        <tr>
          <th style="width:32px"></th>
          <th class="sort" onclick="sortBy('priority')">Priority</th>
          <th class="sort" onclick="sortBy('name')">Resource</th>
          <th>Type</th>
          <th>Region</th>
          <th class="sort" onclick="sortBy('cost')">Cost / mo</th>
          <th>Last activity</th>
        </tr>
      </thead>
      <tbody id="tbody">
        {rows_html}
      </tbody>
    </table>
    <div class="footer">
      <span>Generated by <a href="https://github.com/vamshisiddarth/argus">Argus</a> &nbsp;·&nbsp; Self-contained HTML, works offline</span>
      <a href="#" onclick="downloadJson(event)">&#8595; Download JSON</a>
    </div>
  </div>
</div>

<script>
var RAW_JSON = {_json_data(report)};

function toggle(btn) {{
  var row = btn.closest('tr');
  var detail = row.nextElementSibling;
  var inner = detail.querySelector('.detail-inner');
  var open = inner.classList.contains('open');
  inner.classList.toggle('open', !open);
  btn.textContent = open ? '›' : '⌄';
}}

var sortState = {{col: 'cost', asc: false}};

function sortBy(col) {{
  if (sortState.col === col) sortState.asc = !sortState.asc;
  else {{ sortState.col = col; sortState.asc = col !== 'cost'; }}
  applyFilters();
}}

var PRIORITY_ORDER = {{high: 0, medium: 1, low: 2}};

function applyFilters() {{
  var p = document.getElementById('f-priority').value.toLowerCase();
  var t = document.getElementById('f-type').value.toLowerCase();
  var s = document.getElementById('f-search').value.toLowerCase();
  var tbody = document.getElementById('tbody');
  var rows = Array.from(tbody.querySelectorAll('tr[data-priority]'));

  rows.forEach(function(row) {{
    var dp = row.dataset.priority || '';
    var dt = (row.dataset.rtype || '').toLowerCase();
    var txt = row.textContent.toLowerCase();
    var match = (!p || dp === p) && (!t || dt.includes(t)) && (!s || txt.includes(s));
    row.style.display = match ? '' : 'none';
    var detail = row.nextElementSibling;
    if (detail && detail.classList.contains('detail-row')) {{
      detail.style.display = match ? '' : 'none';
      if (!match) detail.querySelector('.detail-inner').classList.remove('open');
    }}
  }});

  var visible = rows.filter(function(r) {{ return r.style.display !== 'none'; }});

  visible.sort(function(a, b) {{
    var col = sortState.col;
    var av, bv;
    if (col === 'cost') {{
      av = parseFloat(a.dataset.cost || 0);
      bv = parseFloat(b.dataset.cost || 0);
    }} else if (col === 'priority') {{
      av = PRIORITY_ORDER[a.dataset.priority] || 99;
      bv = PRIORITY_ORDER[b.dataset.priority] || 99;
    }} else {{
      av = (a.dataset.name || '').toLowerCase();
      bv = (b.dataset.name || '').toLowerCase();
    }}
    if (av < bv) return sortState.asc ? -1 : 1;
    if (av > bv) return sortState.asc ? 1 : -1;
    return 0;
  }});

  visible.forEach(function(row) {{
    var detail = row.nextElementSibling;
    tbody.appendChild(row);
    if (detail && detail.classList.contains('detail-row')) tbody.appendChild(detail);
  }});

  document.getElementById('count-label').textContent =
    'Showing ' + visible.length + ' of ' + rows.length + ' findings';
}}

function downloadJson(e) {{
  e.preventDefault();
  var blob = new Blob([JSON.stringify(RAW_JSON, null, 2)], {{type: 'application/json'}});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'argus-report-' + RAW_JSON.scan_id.slice(0, 8) + '.json';
  a.click();
}}
</script>
</body>
</html>"""


def _build_rows(findings: list[dict[str, Any]]) -> str:
    registry = get_registry()
    parts: list[str] = []
    for f in findings:
        priority = (f.get("priority") or "low").lower()
        resource_id = html.escape(f.get("resource_id") or "")
        name = html.escape(f.get("name") or "")
        raw_type = f.get("resource_type") or ""
        rtype = html.escape(raw_type)  # used in data-rtype for JS filtering
        rtype_label = html.escape(registry.display_name(raw_type))
        region = html.escape(f.get("region") or "")
        cost = f.get("estimated_monthly_cost") or 0.0
        waste_reason = html.escape(f.get("waste_reason") or "")
        recommendation = html.escape(f.get("recommendation") or "")
        last_activity = f.get("last_activity")
        if last_activity:
            try:
                dt = datetime.fromisoformat(str(last_activity).replace("Z", "+00:00"))
                delta = datetime.now(tz=timezone.utc) - dt
                days = delta.days
                last_activity_str = f"{days}d ago" if days >= 0 else "—"
            except (ValueError, TypeError):
                last_activity_str = html.escape(str(last_activity))
        else:
            last_activity_str = "—"

        display_name = name or resource_id
        cost_class = f"cost-{priority}"
        pill_class = f"pill-{priority}"

        parts.append(
            f"""<tr data-priority="{priority}" data-rtype="{rtype}" data-cost="{cost}" data-name="{display_name}">
  <td><button class="expand-btn" onclick="toggle(this)" aria-label="expand">›</button></td>
  <td><span class="pill {pill_class}">{priority.upper()}</span></td>
  <td><span class="mono">{display_name}</span>{"<br><span class='mono muted'>" + resource_id + "</span>" if name else ""}</td>
  <td class="muted">{rtype_label}</td>
  <td class="muted">{region}</td>
  <td class="{cost_class}">${cost:,.2f}</td>
  <td class="muted">{last_activity_str}</td>
</tr>
<tr class="detail-row">
  <td colspan="7"><div class="detail-inner">
    <span class="detail-label">Why idle:</span>{waste_reason}<br>
    <span class="detail-label">Recommendation:</span>{recommendation}
  </div></td>
</tr>"""
        )
    return "\n".join(parts)


def _build_errors_banner(
    scan_errors: list[dict[str, str]], accounts_succeeded: int
) -> str:
    if not scan_errors:
        return ""
    total = accounts_succeeded + len(scan_errors)
    items = ""
    for err in scan_errors:
        name = html.escape(err.get("account_name") or err.get("account_id", "unknown"))
        reason = html.escape(err.get("error", "unknown error"))
        items += f"<li><code>{name}</code> — {reason}</li>"
    return (
        f'  <div class="error-banner">\n'
        f'    <div class="error-banner-title">'
        f"⚠️ Partial scan — {accounts_succeeded}/{total} "
        f"account{'s' if total != 1 else ''} succeeded"
        f"</div>\n"
        f"    <ul>{items}</ul>\n"
        f"  </div>\n"
    )


def _build_type_options(findings: list[dict[str, Any]]) -> str:
    registry = get_registry()
    types = sorted(
        {f.get("resource_type") or "" for f in findings if f.get("resource_type")}
    )
    return "\n".join(
        f'<option value="{html.escape(t)}">{html.escape(registry.display_name(t))}</option>'
        for t in types
    )


def _json_data(report: dict[str, Any]) -> str:
    import json

    return json.dumps(report, default=str)
