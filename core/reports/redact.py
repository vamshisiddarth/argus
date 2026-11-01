"""
Client-safe view of a scan report: what an agency can show its client.

Applied to a copy of the report before rendering; the stored report is never
changed. Account identifiers become stable aliases, ARNs lose their partition
and account, the agency's own run cost is dropped, and chosen tag keys are
removed. Resource names, types and regions are kept.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

_ARN = re.compile(
    r"arn:aws[a-z-]*:([a-z0-9-]+):([a-z0-9-]*):([0-9]{12}|aws|):([^\s\"'<>,;)]+)"
)
_ACCOUNT_12 = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")
_GUID = re.compile(
    r"(?<![0-9a-fA-F-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F-])"
)

_RUN_COST_KEYS = (
    "llm_spent_usd",
    "llm_budget_usd",
    "llm_estimate_usd",
    "llm_calibration",
)


@dataclass(frozen=True)
class RedactionProfile:
    hide_accounts: bool = True
    shorten_arns: bool = True
    hide_run_cost: bool = True
    hide_identity: bool = True
    hide_tag_keys: frozenset[str] = field(default_factory=frozenset)
    hide_all_tags: bool = False


CLIENT_SAFE = RedactionProfile()


def redact_report(
    report: dict[str, Any], profile: RedactionProfile = CLIENT_SAFE
) -> dict[str, Any]:
    """Return a redacted deep copy of the report."""
    out = copy.deepcopy(report)
    aliases = _aliases(out) if profile.hide_accounts else {}

    if profile.hide_run_cost:
        win = out.get("scan_window")
        if isinstance(win, dict):
            for key in _RUN_COST_KEYS:
                win.pop(key, None)
        for key in ("llm_cost_usd", "token_usage"):
            out.pop(key, None)
        out["redaction"] = {"run_cost_hidden": True}
    if profile.hide_identity:
        _drop_identity_checks(out)

    out = _walk(out, lambda s: _redact_text(s, aliases, profile))
    if profile.hide_all_tags or profile.hide_tag_keys:
        _drop_tags(out, profile)
    return out  # type: ignore[no-any-return]


def _aliases(report: dict[str, Any]) -> dict[str, str]:
    ids: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and value:
            ids.add(value)

    for item in report.get("accounts_scanned") or []:
        add(item if isinstance(item, str) else (item or {}).get("id"))
    for f in report.get("findings") or []:
        add(f.get("account_id"))
    for opp in report.get("opportunities") or []:
        for a in opp.get("accounts") or []:
            add(a)
    for e in report.get("scan_errors") or []:
        add(e.get("account_id"))
    for acct in (report.get("preflight") or {}).get("accounts") or []:
        add(acct.get("account_id"))
    return {raw: f"account-{i}" for i, raw in enumerate(sorted(ids), 1)}


def _redact_text(text: str, aliases: dict[str, str], p: RedactionProfile) -> str:
    if p.shorten_arns:
        text = _ARN.sub(_short_arn, text)
    for raw in sorted(aliases, key=len, reverse=True):
        text = text.replace(raw, aliases[raw])
    if p.hide_accounts:
        text = _ACCOUNT_12.sub("account", text)
        text = _GUID.sub("subscription", text)
    return text


def _short_arn(m: re.Match[str]) -> str:
    service, region, _account, rest = m.groups()
    return f"{service}:{region}:{rest}" if region else f"{service}:{rest}"


def _walk(value: Any, fn: Any) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_walk(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v, fn) for k, v in value.items()}
    return value


def _drop_identity_checks(report: dict[str, Any]) -> None:
    pre = report.get("preflight")
    if not isinstance(pre, dict):
        return
    for acct in pre.get("accounts") or []:
        acct["checks"] = [
            c for c in acct.get("checks") or [] if c.get("code") != "P1_IDENTITY"
        ]


def _drop_tags(report: dict[str, Any], p: RedactionProfile) -> None:
    hide = {k.lower() for k in p.hide_tag_keys}
    for f in report.get("findings") or []:
        tags = f.get("tags")
        if not isinstance(tags, dict):
            continue
        f["tags"] = (
            {}
            if p.hide_all_tags
            else {k: v for k, v in tags.items() if str(k).lower() not in hide}
        )
    for opp in report.get("opportunities") or []:
        owners = opp.get("owners")
        if isinstance(owners, list):
            if p.hide_all_tags:
                opp["unowned_count"] = 0
            opp["owners"] = (
                []
                if p.hide_all_tags
                else [o for o in owners if str(o.get("tag", "")).lower() not in hide]
            )
