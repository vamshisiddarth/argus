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
from core.pricing.aws import (
    ALB_MONTHLY,
    CLB_MONTHLY,
    EIP_MONTHLY,
    NAT_GATEWAY_MONTHLY,
    ebs_volume_monthly,
)

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
        list_price_usd=NAT_GATEWAY_MONTHLY,
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
        list_price_usd=ALB_MONTHLY,
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
        list_price_usd=CLB_MONTHLY,
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


@dataclass(frozen=True)
class StateRule:
    """A rule decided by a resource's current configuration, not by its metrics."""

    rule_id: str
    resource_type: str
    # True = wasteful, False = fine, None = state incomplete, cannot tell
    is_waste: Callable[[dict[str, Any]], bool | None]
    monthly_cost: Callable[[dict[str, Any]], float]
    reason: Callable[[dict[str, Any]], str]
    recommendation: str
    confidence: str


def _volume_cost(state: dict[str, Any]) -> float:
    return ebs_volume_monthly(
        state.get("size_gb"),
        state.get("volume_type", "gp2"),
        state.get("iops"),
        state.get("throughput"),
    )


def _volume_unattached(state: dict[str, Any]) -> bool | None:
    value = state.get("state")
    return None if value is None else value == "available"


def _eip_unassociated(state: dict[str, Any]) -> bool | None:
    value = state.get("associated")
    return None if value is None else not value


def _instance_stopped(state: dict[str, Any]) -> bool | None:
    value = state.get("state")
    return None if value is None else value == "stopped"


def _stopped_instance_cost(state: dict[str, Any]) -> float:
    return round(
        sum(
            ebs_volume_monthly(v.get("size_gb"), v.get("volume_type", "gp2"))
            for v in state.get("volumes", [])
        ),
        2,
    )


STATE_RULES: tuple[StateRule, ...] = (
    StateRule(
        rule_id="ebs-volume-unattached",
        resource_type="AWS::EC2::Volume",
        is_waste=_volume_unattached,
        monthly_cost=_volume_cost,
        reason=lambda s: (
            f"This {s.get('size_gb')} GiB {s.get('volume_type')} volume is "
            "unattached (state: available) and still billed for its storage."
        ),
        recommendation=(
            "Snapshot it if the data might matter, confirm nothing expects it, then "
            "delete the volume."
        ),
        confidence="high",
    ),
    StateRule(
        rule_id="elastic-ip-unassociated",
        resource_type="AWS::EC2::EIP",
        is_waste=_eip_unassociated,
        monthly_cost=lambda s: EIP_MONTHLY,
        reason=lambda s: (
            "This Elastic IP is not associated with any instance or network "
            "interface; AWS bills every public IPv4 address."
        ),
        recommendation=(
            "Release the address after checking that no DNS record or allow-list "
            "still points at it."
        ),
        confidence="high",
    ),
    StateRule(
        rule_id="ec2-instance-stopped",
        resource_type="AWS::EC2::Instance",
        is_waste=_instance_stopped,
        monthly_cost=_stopped_instance_cost,
        reason=lambda s: (
            f"This {s.get('instance_type', 'instance')} is stopped but its attached "
            "EBS volumes are still billed."
        ),
        recommendation=(
            "If it is no longer needed, create an AMI and terminate it; if it is "
            "needed, start it or schedule it."
        ),
        confidence="medium",
    ),
)

STATE_RULES_BY_TYPE: dict[str, StateRule] = {r.resource_type: r for r in STATE_RULES}
