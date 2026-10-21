"""
Deterministic choice of which discovered resources go to the AI when the
per-scan cap truncates the inventory.

Rules:
  * With cost data: keep a floor of two resources per type, fill the rest by
    cost descending.
  * Without cost data: round-robin across types (sorted by name), one per pass;
    after the first pass, high-impact types take two per pass. Cheap types are
    never crowded out entirely.
Ties always break on resource_id, so the same inputs give the same output.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from adapters.base import Resource

SelectionRule = Literal["cost_desc", "stratified_by_type"]

HIGH_IMPACT_TYPES: frozenset[str] = frozenset(
    {
        "AWS::EC2::NatGateway",
        "AWS::EC2::Instance",
        "AWS::RDS::DBInstance",
        "AWS::RDS::DBCluster",
        "AWS::ElastiCache::CacheCluster",
        "AWS::ElastiCache::ReplicationGroup",
        "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "AWS::ElasticLoadBalancing::LoadBalancer",
    }
)

_FLOOR_PER_TYPE = 2


def select_candidates(
    resources: list[Resource], costs: dict[str, float], cap: int
) -> tuple[list[Resource], SelectionRule]:
    """Return (chosen, rule). Chosen is ordered by cost descending, then id."""
    has_cost = any(v > 0 for v in costs.values())
    rule: SelectionRule = "cost_desc" if has_cost else "stratified_by_type"

    def cost_of(r: Resource) -> float:
        return costs.get(r.resource_id, 0.0)

    def order(r: Resource) -> tuple[float, str]:
        return (-cost_of(r), r.resource_id)

    if cap >= len(resources):
        return sorted(resources, key=order), rule

    by_type: dict[str, list[Resource]] = defaultdict(list)
    for r in resources:
        by_type[r.resource_type].append(r)
    for items in by_type.values():
        items.sort(key=order)
    types = sorted(by_type)

    chosen: list[Resource] = []
    taken: set[str] = set()

    def take(r: Resource) -> bool:
        if len(chosen) >= cap or r.resource_id in taken:
            return False
        chosen.append(r)
        taken.add(r.resource_id)
        return True

    if has_cost:
        # Floor per type, shrunk when it would eat the whole cap, and walked in
        # order of each type's top cost so the costliest types are never starved.
        floor = min(_FLOOR_PER_TYPE, max(1, cap // len(types)))
        for t in sorted(types, key=lambda t: (order(by_type[t][0]), t)):
            for r in by_type[t][:floor]:
                take(r)
        for r in sorted(resources, key=order):
            take(r)
    else:
        queues = {t: list(by_type[t]) for t in types}
        first_pass = True
        while len(chosen) < cap and any(queues.values()):
            for t in types:
                per_pass = 2 if (t in HIGH_IMPACT_TYPES and not first_pass) else 1
                for _ in range(per_pass):
                    if queues[t]:
                        take(queues[t].pop(0))
            first_pass = False

    return sorted(chosen, key=order), rule
