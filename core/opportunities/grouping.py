"""
Deterministic grouping of findings into opportunities.

Key: action x resource family x tier. The tier separates findings that need a
human look (flagged) from unsure ones (low confidence) from sure ones, so one
doubtful member cannot hold a whole group out of the easy lane. Owners are
listed, never used as a key (splitting by owner turned 499 findings into 114
groups in a real scan). Groups below a minimum size collapse into one "other"
bucket per action and tier; if the list is still too long the minimum is raised
until it fits.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from typing import Any

from core.opportunities.actions import (
    REMOVE,
    RETENTION,
    STOP,
    classify_action,
    family_of,
)
from core.opportunities.guidance import build_guidance
from core.registry import get_registry
from core.reports.basis import (
    BILLED,
    LIST_PRICE,
    MODEL_ESTIMATE,
    cost_summary,
)

DEFAULT_MIN_GROUP_SIZE = 2
DEFAULT_MAX_OPPORTUNITIES = 50
OWNER_TAGS = ("team", "owner", "project", "application", "service")

_PRIORITY = {"low": 0, "medium": 1, "high": 2}
_CONFIDENCE = {"low": 0, "medium": 1, "high": 2}
_EASY_ACTIONS = {REMOVE, STOP, RETENTION}
_LANE_ORDER = {"easy": 0, "doubt": 1}
_VERB_TEXT = {
    "remove": "Remove",
    "stop": "Stop",
    "rightsize": "Right-size",
    "retention": "Set retention on",
    "review": "Review",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{5,}")

Key = tuple[str, str, str]


def build_opportunity_block(
    findings: list[dict[str, Any]],
    min_group_size: int = DEFAULT_MIN_GROUP_SIZE,
    max_opportunities: int = DEFAULT_MAX_OPPORTUNITIES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The opportunities and their summary, ready to put in a report."""
    opps, used = _group(findings, min_group_size, max_opportunities)
    return opps, opportunity_summary(findings, opps, used, max_opportunities)


def build_opportunities(
    findings: list[dict[str, Any]],
    min_group_size: int = DEFAULT_MIN_GROUP_SIZE,
    max_opportunities: int = DEFAULT_MAX_OPPORTUNITIES,
) -> list[dict[str, Any]]:
    return _group(findings, min_group_size, max_opportunities)[0]


def opportunity_summary(
    findings: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    min_group_size: int = DEFAULT_MIN_GROUP_SIZE,
    max_opportunities: int = DEFAULT_MAX_OPPORTUNITIES,
) -> dict[str, Any]:
    lanes = {"easy": 0, "doubt": 0}
    for o in opportunities:
        lanes[o["lane"]] += 1
    other = sum(
        o["member_count"] for o in opportunities if o["key"]["family"] == "other"
    )
    count = len(opportunities)
    return {
        "findings": len(findings),
        "opportunities": count,
        "reduction_ratio": round(len(findings) / count, 2) if count else None,
        "lanes": lanes,
        "largest_members": max((o["member_count"] for o in opportunities), default=0),
        "other_bucket_members": other,
        "min_group_size": min_group_size,
        "max_opportunities": max_opportunities,
    }


def _group(
    findings: list[dict[str, Any]], min_size: int, max_opps: int
) -> tuple[list[dict[str, Any]], int]:
    if not findings:
        return [], min_size
    raw: dict[Key, list[dict[str, Any]]] = defaultdict(list)
    for f in findings:
        raw[_key(f)].append(f)
    largest = max(len(v) for v in raw.values())
    size = max(1, min_size)
    while True:
        groups = _collapse(raw, size)
        if not max_opps or len(groups) <= max_opps or size > largest:
            break
        size += 1
    opps = [_make(key, members) for key, members in groups.items()]
    _link_related(opps, groups)
    opps.sort(
        key=lambda o: (_LANE_ORDER[o["lane"]], -o["savings"]["high_usd"], o["id"])
    )
    return opps, size


def _tier(f: dict[str, Any]) -> str:
    if f.get("review_required"):
        return "flagged"
    if str(f.get("confidence") or "low") in ("medium", "high"):
        return "sure"
    return "unsure"


def _key(f: dict[str, Any]) -> Key:
    return (classify_action(f), family_of(str(f.get("resource_type") or "")), _tier(f))


def _collapse(
    raw: dict[Key, list[dict[str, Any]]], min_size: int
) -> dict[Key, list[dict[str, Any]]]:
    out: dict[Key, list[dict[str, Any]]] = defaultdict(list)
    for (action, family, tier), members in raw.items():
        target = (
            (action, family, tier)
            if len(members) >= min_size
            else (action, "other", tier)
        )
        out[target].extend(members)
    return dict(out)


def _cost(f: dict[str, Any]) -> float:
    return float(f.get("estimated_monthly_cost") or 0.0)


def _make(key: Key, members: list[dict[str, Any]]) -> dict[str, Any]:
    action, family, tier = key
    ordered = sorted(members, key=lambda f: (-_cost(f), str(f["resource_id"])))
    summary = cost_summary(ordered)
    by_basis = summary["waste_by_basis"]
    low = by_basis[BILLED] + by_basis[LIST_PRICE]
    owners, unowned = _owners(ordered)
    flagged = sum(1 for f in ordered if f.get("review_required"))
    confidence = min(
        (str(f.get("confidence") or "low") for f in ordered),
        key=lambda c: _CONFIDENCE.get(c, 0),
    )
    priority = max(
        (str(f.get("priority") or "low") for f in ordered),
        key=lambda p: _PRIORITY.get(p, 0),
    )
    easy = action in _EASY_ACTIONS and tier == "sure"
    return {
        "id": _opp_id(key),
        "key": {"action": action, "family": family, "tier": tier},
        "title": _title(action, family, ordered),
        "action": action,
        "lane": "easy" if easy else "doubt",
        "resource_types": sorted({str(f.get("resource_type")) for f in ordered}),
        "accounts": sorted(
            {str(f["account_id"]) for f in ordered if f.get("account_id")}
        ),
        "regions": sorted({str(f["region"]) for f in ordered if f.get("region")}),
        "owners": owners,
        "unowned_count": unowned,
        "member_count": len(ordered),
        "members": [str(f["resource_id"]) for f in ordered],
        "savings": {
            "low_usd": round(low, 2),
            "high_usd": round(low + by_basis[MODEL_ESTIMATE], 2),
            "by_basis": by_basis,
            "unpriced": summary["unpriced_findings"],
        },
        "priority": priority,
        "confidence": confidence,
        "review_required_count": flagged,
        "risk_reasons": sorted(
            {r for f in ordered for r in (f.get("review_reasons") or [])}
        ),
        **build_guidance(action, ordered, confidence, summary),
        "related": [],
    }


def _opp_id(key: Key) -> str:
    digest = hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()
    return f"opp-{digest[:12]}"


def _owners(findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    counts: Counter[tuple[str, str]] = Counter()
    unowned = 0
    for f in findings:
        tags = {str(k).lower(): str(v) for k, v in (f.get("tags") or {}).items() if v}
        for tag in OWNER_TAGS:
            if tags.get(tag):
                counts[(tag, tags[tag])] += 1
                break
        else:
            unowned += 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return [{"tag": t, "value": v, "count": n} for (t, v), n in top], unowned


_ACRONYMS = frozenset(
    "ec2 ebs eip vpn nat rds ecs eks ecr efs s3 sqs sns kms vpc waf iam elb alb nlb "
    "dns cdn sso api".split()
)
_SERVICE_NAMES = {
    "logs": "CloudWatch",
    "es": "OpenSearch",
    "elasticfilesystem": "EFS",
    "elasticache": "ElastiCache",
    "secretsmanager": "Secrets Manager",
    "apigateway": "API Gateway",
    "cloudfront": "CloudFront",
    "kafka": "MSK",
}


def _words(text: str) -> str:
    parts = text.replace("/", " ").replace("-", " ").split()
    return " ".join(p.upper() if p.lower() in _ACRONYMS else p for p in parts)


def _humanize(type_id: str) -> str:
    named = get_registry().display_name(type_id)
    if named != type_id:
        return named
    if "::" in type_id:
        return _words(" ".join(type_id.split("::")[1:]))
    if ":" in type_id:
        service, rest = type_id.split(":", 1)
        label = _SERVICE_NAMES.get(service) or (
            service.upper() if service in _ACRONYMS else service.capitalize()
        )
        return f"{label} {_words(rest)}"
    return type_id


def _plural(noun: str, n: int) -> str:
    return noun if n == 1 or noun.endswith("s") else f"{noun}s"


def _title(action: str, family: str, members: list[dict[str, Any]]) -> str:
    n = len(members)
    verb = _VERB_TEXT.get(action, "Review")
    if family == "other":
        noun = "other resource" if n == 1 else "other resources"
    elif family == "snapshot":
        noun = "snapshot" if n == 1 else "snapshots"
    else:
        noun = _plural(_humanize(str(members[0].get("resource_type"))), n)
    return f"{verb} {n} {noun}"


def _link_related(
    opps: list[dict[str, Any]], groups: dict[Key, list[dict[str, Any]]]
) -> None:
    """Soft links: one finding's text names another finding's resource id."""
    owner_of: dict[str, str] = {}
    by_id = {o["id"]: o for o in opps}
    for key, members in groups.items():
        oid = _opp_id(key)
        for f in members:
            short = str(f["resource_id"]).split("/")[-1]
            if len(short) >= 6:
                owner_of[short] = oid
    for key, members in groups.items():
        oid = _opp_id(key)
        for f in members:
            text = f"{f.get('waste_reason') or ''} {f.get('recommendation') or ''}"
            for token in set(_TOKEN_RE.findall(text)):
                other = owner_of.get(token.rstrip(".:-_"))
                if other and other != oid:
                    _add_link(by_id[oid], other)
                    _add_link(by_id[other], oid)


def _add_link(opp: dict[str, Any], other: str) -> None:
    if other not in opp["related"]:
        opp["related"] = sorted([*opp["related"], other])
