"""Checks on model findings that the evidence cannot support.

A collector that returned nothing is not evidence that a resource is idle, and a
cache node that is a failover replica is not waste because it serves no reads.
Findings that fail these checks are withheld from the waste total and reported
as "could not judge", with the reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.pipeline.triage import Flagged

# Resources whose cost is a standing charge and whose use shows only in traffic
# metrics. Matched on the type id with punctuation and case removed, so cloud
# native names ("ec2:vpc-endpoint") and registry ids both match.
_TRAFFIC_TYPES = (
    "natgateway",
    "clientvpn",
    "transitgateway",
    "vpcendpoint",
    "vpnconnection",
    "vpngateway",
    "vpntunnel",
    "loadbalancer",
    "webacl",
    "networkfirewall",
    "applicationgateway",
    "azurefirewall",
    "virtualnetworkgateway",
    "googleapiscomrouter",
)
_CACHE_TYPES = frozenset(
    {"AWS::ElastiCache::CacheCluster", "AWS::ElastiCache::ReplicationGroup"}
)
_SNAPSHOT_TYPE = "ec2:snapshot"
_PROTECT_WORDS = (
    "retain",
    "retention",
    "backup",
    "keep",
    "safety",
    "donotdelete",
    "dontdelete",
    "legal",
    "compliance",
    "archive",
)


_Hold = Callable[[str, str], "Withheld"]


@dataclass(frozen=True)
class Withheld:
    resource_id: str
    resource_type: str
    kind: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "kind": self.kind,
            "reason": self.reason,
        }


def screen(
    flagged: list[Flagged], activity_days: int = 90
) -> tuple[list[Flagged], list[Withheld]]:
    kept: list[Flagged] = []
    withheld: list[Withheld] = []
    for flag in flagged:
        hit = _check(flag, activity_days)
        if hit is None:
            kept.append(flag)
        else:
            withheld.append(hit)
    return kept, withheld


def needs_traffic_metrics(resource_type: str, native_type: str | None) -> bool:
    text = _squash(f"{resource_type} {native_type or ''}")
    return any(token in text for token in _TRAFFIC_TYPES)


def _check(flag: Flagged, activity_days: int = 90) -> Withheld | None:
    ev = flag.evidence
    r = ev.resource

    def hold(kind: str, reason: str) -> Withheld:
        return Withheld(r.resource_id, r.resource_type, kind, reason)

    if needs_traffic_metrics(r.resource_type, r.native_type) and (
        ev.metrics_status != "ok"
    ):
        return hold(
            "no_metrics",
            "Traffic metrics were unavailable, so idleness cannot be judged. "
            "Check the resource's traffic before acting.",
        )
    if r.resource_type in _CACHE_TYPES:
        return _check_cache(flag, hold)
    if r.resource_type == _SNAPSHOT_TYPE:
        return _check_snapshot(flag, hold)
    if is_log_group(r.resource_type, r.native_type):
        return _check_log_group(flag, hold, activity_days)
    rds = _rds_kind(r.resource_type, r.native_type)
    if rds == "auto_backup":
        return hold(
            "automated_snapshot",
            "An automated backup is managed by AWS retention; it is not a delete "
            "candidate.",
        )
    if rds == "snapshot":
        return _check_rds_snapshot(flag, hold)
    return None


def _check_cache(flag: Flagged, hold: _Hold) -> Withheld | None:
    ev = flag.evidence
    state = ev.state
    if state is None:
        return hold(
            "state_unavailable",
            "Replication settings could not be read, so a failover replica cannot "
            "be ruled out.",
        )
    if state.get("kind") != "elasticache_node":
        return None
    failover = state.get("automatic_failover") in ("enabled", "enabling")
    multi_az = state.get("multi_az") in ("enabled", "enabling")
    if state.get("replication_group") and (failover or multi_az):
        role = state.get("role", "unknown")
        return hold(
            "failover_replica",
            f"This node is a {role} in replication group "
            f"{state['replication_group']} with failover enabled. Judge the group, "
            "not a single node.",
        )
    return None


def _check_snapshot(flag: Flagged, hold: _Hold) -> Withheld | None:
    ev = flag.evidence
    state = ev.state
    if state is None:
        return hold(
            "state_unavailable",
            "Snapshot details could not be read, so AMI use cannot be ruled out.",
        )
    if state.get("ami_backed"):
        return hold(
            "ami_backed",
            f"An AMI ({state.get('ami', 'unknown')}) still uses this snapshot.",
        )
    tags = " ".join(f"{k} {v}" for k, v in ev.resource.tags.items())
    squashed = _squash(tags)
    if any(word in squashed for word in _PROTECT_WORDS):
        return hold(
            "protected_by_tag",
            "A tag marks this snapshot as a retained or safety copy.",
        )
    return None


def is_log_group(resource_type: str, native_type: str | None = None) -> bool:
    return "loggroup" in _squash(f"{resource_type} {native_type or ''}")


def _rds_kind(resource_type: str, native_type: str | None) -> str | None:
    text = _squash(f"{resource_type} {native_type or ''}")
    if "rdsautobackup" in text:
        return "auto_backup"
    if any(t in text for t in ("rdssnapshot", "rdsclustersnapshot", "dbsnapshot")):
        return "snapshot"
    return None


def _check_log_group(flag: Flagged, hold: _Hold, activity_days: int) -> Withheld | None:
    ev = flag.evidence
    if not ev.activity_checked:
        return hold(
            "activity_unverified",
            "Log activity could not be read, so a claim of no recent activity "
            "cannot be made.",
        )
    last = ev.last_activity
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if datetime.now(tz=timezone.utc) - last <= timedelta(days=activity_days):
            return hold(
                "recent_log_activity",
                f"The group received log events on {last.date().isoformat()}, "
                f"within the last {activity_days} days.",
            )
    return None


def _check_rds_snapshot(flag: Flagged, hold: _Hold) -> Withheld | None:
    ev = flag.evidence
    state = ev.state
    if state is None:
        return hold(
            "state_unavailable",
            "Snapshot details could not be read, so an automated snapshot cannot "
            "be ruled out.",
        )
    kind = str(state.get("snapshot_type") or "").lower()
    if kind in ("automated", "awsbackup"):
        return hold(
            "automated_snapshot",
            "An AWS-managed snapshot (type "
            f"{kind}) is subject to retention; it is not a delete candidate.",
        )
    squashed = _squash(" ".join(f"{k} {v}" for k, v in ev.resource.tags.items()))
    if any(word in squashed for word in _PROTECT_WORDS):
        return hold(
            "protected_by_tag",
            "A tag marks this snapshot as a retained or safety copy.",
        )
    return None


def _squash(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())
