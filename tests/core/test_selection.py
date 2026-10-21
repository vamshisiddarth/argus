import random
from collections import Counter

from adapters.base import Resource
from core.agent.selection import HIGH_IMPACT_TYPES, select_candidates

NAT = "AWS::EC2::NatGateway"
VOL = "AWS::EC2::Volume"
SNAP = "AWS::EC2::Snapshot"
ZONE = "AWS::Route53::HostedZone"
FN = "AWS::Lambda::Function"


def _res(rtype: str, n: int, prefix: str | None = None) -> list[Resource]:
    prefix = prefix or rtype.split("::")[-1].lower()
    return [
        Resource(
            resource_id=f"{prefix}-{i:02d}",
            resource_type=rtype,
            cloud="aws",
            region="us-east-1",
            tags={},
        )
        for i in range(n)
    ]


def _types(resources: list[Resource]) -> Counter:
    return Counter(r.resource_type for r in resources)


def test_nat_is_high_impact():
    assert NAT in HIGH_IMPACT_TYPES


def test_no_cost_data_round_robins_all_types():
    resources = _res(VOL, 4) + _res(SNAP, 4) + _res(ZONE, 4)

    chosen, rule = select_candidates(resources, {}, cap=6)

    assert rule == "stratified_by_type"
    assert _types(chosen) == {VOL: 2, SNAP: 2, ZONE: 2}


def test_cap_smaller_than_type_count_is_deterministic():
    types = [f"AWS::Test::Type{c}" for c in "EDCBA"]
    resources = [r for t in types for r in _res(t, 2)]

    expected = None
    for seed in range(10):
        shuffled = resources[:]
        random.Random(seed).shuffle(shuffled)
        chosen, _ = select_candidates(shuffled, {}, cap=3)
        ids = [r.resource_id for r in chosen]
        expected = expected or ids
        assert ids == expected

    assert {r.resource_type for r in chosen} == {
        "AWS::Test::TypeA",
        "AWS::Test::TypeB",
        "AWS::Test::TypeC",
    }


def test_high_impact_types_get_extra_picks_only_after_first_pass():
    resources = _res(NAT, 10) + _res(VOL, 10) + _res(ZONE, 10)

    chosen, _ = select_candidates(resources, {}, cap=7)

    # pass 1: one each (3). pass 2: NAT takes two, others one (4).
    assert _types(chosen) == {NAT: 3, VOL: 2, ZONE: 2}


def test_with_cost_data_keeps_floor_per_type_then_fills_by_cost():
    expensive = _res(NAT, 8)
    resources = expensive + _res(VOL, 4) + _res(ZONE, 4)
    costs = {r.resource_id: 100.0 - i for i, r in enumerate(expensive)}

    chosen, rule = select_candidates(resources, costs, cap=6)

    assert rule == "cost_desc"
    counts = _types(chosen)
    assert set(counts) == {NAT, VOL, ZONE}
    # floor of 2 for VOL and ZONE, the other 2 slots go to the costliest NATs
    assert counts == {NAT: 2, VOL: 2, ZONE: 2}
    assert {r.resource_id for r in chosen if r.resource_type == NAT} == {
        "natgateway-00",
        "natgateway-01",
    }


def test_cap_not_smaller_than_input_returns_everything():
    resources = _res(VOL, 3) + _res(FN, 2)

    chosen, _ = select_candidates(resources, {}, cap=10)

    assert len(chosen) == 5


def test_ties_broken_by_resource_id():
    resources = list(reversed(_res(VOL, 5)))

    chosen, _ = select_candidates(resources, {}, cap=3)

    assert [r.resource_id for r in chosen] == ["volume-00", "volume-01", "volume-02"]
