from __future__ import annotations

from adapters.base import Resource
from core.pipeline.evidence import Evidence
from core.pipeline.guards import needs_traffic_metrics, screen
from core.pipeline.triage import Flagged


def _flag(rtype, native=None, status="no_data", state=None, tags=None, rid="r-1"):
    res = Resource(
        resource_id=rid,
        resource_type=rtype,
        cloud="aws",
        region="eu-west-1",
        tags=tags or {},
        native_type=native or rtype,
    )
    ev = Evidence(resource=res, metrics_status=status, state=state)
    return Flagged(0, ev, "idle", "delete", "high", "high", 38.0)


def _kinds(flags):
    kept, withheld = screen(flags)
    return len(kept), [w.kind for w in withheld]


class TestNoMetricsIsNotIdle:
    def test_nat_gateway_without_metrics_is_withheld(self):
        assert _kinds([_flag("AWS::EC2::NatGateway")]) == (0, ["no_metrics"])

    def test_nat_gateway_with_a_metrics_error_is_withheld(self):
        assert _kinds([_flag("AWS::EC2::NatGateway", status="error")]) == (
            0,
            ["no_metrics"],
        )

    def test_nat_gateway_with_metrics_is_kept(self):
        assert _kinds([_flag("AWS::EC2::NatGateway", status="ok")]) == (1, [])

    def test_unmapped_network_types_are_withheld_too(self):
        for native in (
            "ec2:client-vpn-endpoint",
            "ec2:transit-gateway-attachment",
            "ec2:vpc-endpoint",
        ):
            assert _kinds([_flag(native)]) == (0, ["no_metrics"]), native

    def test_load_balancer_and_waf_without_metrics_are_withheld(self):
        for rtype in (
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
            "AWS::WAFv2::WebACL",
        ):
            assert _kinds([_flag(rtype)]) == (0, ["no_metrics"]), rtype

    def test_other_types_without_metrics_are_unchanged(self):
        assert _kinds([_flag("AWS::Lambda::Function")]) == (1, [])

    def test_matching_ignores_case_and_punctuation(self):
        assert needs_traffic_metrics("x", "EC2:Vpc-Endpoint")


NODE = {
    "kind": "elasticache_node",
    "replication_group": "shared",
    "role": "replica",
    "automatic_failover": "enabled",
    "multi_az": "enabled",
    "group_size": 2,
}


class TestCacheFailover:
    T = "AWS::ElastiCache::CacheCluster"

    def test_replica_with_failover_is_withheld(self):
        assert _kinds([_flag(self.T, status="ok", state=NODE)]) == (
            0,
            ["failover_replica"],
        )

    def test_primary_of_a_failover_group_is_withheld(self):
        node = {**NODE, "role": "primary"}
        assert _kinds([_flag(self.T, status="ok", state=node)]) == (
            0,
            ["failover_replica"],
        )

    def test_standalone_node_is_kept(self):
        node = {
            "kind": "elasticache_node",
            "replication_group": None,
            "role": "standalone",
        }
        assert _kinds([_flag(self.T, status="ok", state=node)]) == (1, [])

    def test_replica_without_failover_or_multi_az_is_kept(self):
        node = {**NODE, "automatic_failover": "disabled", "multi_az": "disabled"}
        assert _kinds([_flag(self.T, status="ok", state=node)]) == (1, [])

    def test_unknown_state_is_withheld(self):
        assert _kinds([_flag(self.T, status="ok", state=None)]) == (
            0,
            ["state_unavailable"],
        )


class TestSnapshots:
    T = "ec2:snapshot"

    def test_ami_backed_snapshot_is_withheld(self):
        state = {"kind": "ebs_snapshot", "ami_backed": True, "ami": "ami-1"}
        assert _kinds([_flag(self.T, state=state)]) == (0, ["ami_backed"])

    def test_safety_copy_tag_is_withheld(self):
        state = {"kind": "ebs_snapshot", "ami_backed": False}
        tags = {"purpose": "pre-migration-safety-copy"}
        assert _kinds([_flag(self.T, state=state, tags=tags)]) == (
            0,
            ["protected_by_tag"],
        )

    def test_unknown_state_is_withheld(self):
        assert _kinds([_flag(self.T)]) == (0, ["state_unavailable"])

    def test_plain_orphan_snapshot_is_kept(self):
        state = {"kind": "ebs_snapshot", "ami_backed": False}
        assert _kinds([_flag(self.T, state=state, tags={"Name": "x"})]) == (1, [])
