"""
Deterministic idle-resource rules.

A rule only fires on metric data we actually received (status ok with every
required metric present); missing data never becomes a finding. List prices are
us-east-1 hourly rates x 730 hours and are replaced by billed cost when known.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from adapters.base import Resource

_HOURS_PER_MONTH = 730
_NAT_IDLE_BYTES = 1_048_576  # under 1 MiB in either direction over the window


@dataclass(frozen=True)
class Rule:
    rule_id: str
    resource_type: str
    applies: Callable[[Resource], bool]
    # True = idle, False = in use, None = metrics incomplete, cannot tell
    is_idle: Callable[[dict[str, Any]], bool | None]
    list_price_usd: float
    reason: Callable[[int], str]
    recommendation: str


def _all_present(metrics: dict[str, Any], *keys: str) -> bool:
    return all(metrics.get(k) is not None for k in keys)


def _nat_idle(m: dict[str, Any]) -> bool | None:
    if not _all_present(m, "BytesOutToDestination", "BytesInFromDestination"):
        return None
    total = float(m["BytesOutToDestination"]) + float(m["BytesInFromDestination"])
    return total < _NAT_IDLE_BYTES


def _alb_idle(m: dict[str, Any]) -> bool | None:
    if m.get("RequestCount") is None:
        return None
    connections = m.get("ActiveConnectionCount")
    return float(m["RequestCount"]) == 0 and (
        connections is None or float(connections) == 0
    )


def _clb_idle(m: dict[str, Any]) -> bool | None:
    if m.get("RequestCount") is None:
        return None
    return float(m["RequestCount"]) == 0


RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="nat-gateway-idle",
        resource_type="AWS::EC2::NatGateway",
        applies=lambda r: True,
        is_idle=_nat_idle,
        list_price_usd=round(0.045 * _HOURS_PER_MONTH, 2),
        reason=lambda days: (
            f"No meaningful traffic through this NAT gateway: under 1 MiB in or "
            f"out over the {days}-day metrics window."
        ),
        recommendation=(
            "Confirm no route table still points at it (aws ec2 describe-route-tables "
            "--filters Name=route.nat-gateway-id,Values=<id>), then delete the NAT "
            "gateway and release its Elastic IP."
        ),
    ),
    Rule(
        rule_id="alb-no-requests",
        resource_type="AWS::ElasticLoadBalancingV2::LoadBalancer",
        applies=lambda r: "/app/" in r.resource_id,  # NLB/GWLB use other namespaces
        is_idle=_alb_idle,
        list_price_usd=round(0.0225 * _HOURS_PER_MONTH, 2),
        reason=lambda days: (
            f"This Application Load Balancer served 0 requests and held 0 active "
            f"connections over the {days}-day metrics window."
        ),
        recommendation=(
            "Confirm no DNS record, WAF association or target group still depends "
            "on it, then delete the load balancer."
        ),
    ),
    Rule(
        rule_id="classic-elb-no-requests",
        resource_type="AWS::ElasticLoadBalancing::LoadBalancer",
        applies=lambda r: True,
        is_idle=_clb_idle,
        list_price_usd=round(0.025 * _HOURS_PER_MONTH, 2),
        reason=lambda days: (
            f"This Classic Load Balancer served 0 requests over the {days}-day "
            f"metrics window."
        ),
        recommendation=(
            "Confirm no DNS record or instance registration still depends on it, "
            "then delete the load balancer."
        ),
    ),
)

RULES_BY_TYPE: dict[str, Rule] = {r.resource_type: r for r in RULES}
