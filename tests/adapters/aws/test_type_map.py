"""Resource Explorer reports `service:type`; Argus's registry, metric tables and
rules are keyed on CloudFormation-style ids. The map must join them."""

import json
from pathlib import Path

import pytest

from adapters.aws.resource_explorer import _is_billable, _parse_resource
from adapters.aws.type_map import canonical_type, is_config_only
from core.registry import get_registry

FIXTURE = Path(__file__).resolve().parent.parent.parent / "fixtures"


@pytest.mark.parametrize(
    ("native", "canonical"),
    [
        ("ec2:instance", "AWS::EC2::Instance"),
        ("ec2:natgateway", "AWS::EC2::NatGateway"),
        ("ec2:volume", "AWS::EC2::Volume"),
        ("rds:db", "AWS::RDS::DBInstance"),
        ("rds:cluster", "AWS::RDS::DBCluster"),
        ("lambda:function", "AWS::Lambda::Function"),
        ("dynamodb:table", "AWS::DynamoDB::Table"),
        ("s3:bucket", "AWS::S3::Bucket"),
        ("sqs:queue", "AWS::SQS::Queue"),
        ("sns:topic", "AWS::SNS::Topic"),
        ("ecs:service", "AWS::ECS::Service"),
        ("route53:hostedzone", "AWS::Route53::HostedZone"),
        ("cloudfront:distribution", "AWS::CloudFront::Distribution"),
        ("elasticache:cluster", "AWS::ElastiCache::CacheCluster"),
        (
            "elasticloadbalancing:loadbalancer/app",
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
        ),
        (
            "elasticloadbalancing:loadbalancer/net",
            "AWS::ElasticLoadBalancingV2::LoadBalancer",
        ),
        (
            "elasticloadbalancing:loadbalancer",
            "AWS::ElasticLoadBalancing::LoadBalancer",
        ),
    ],
)
def test_known_native_types_map_to_registry_ids(native, canonical):
    assert canonical_type(native) == canonical
    assert get_registry().get(canonical) is not None


def test_lookup_is_case_and_whitespace_tolerant():
    assert canonical_type(" EC2:NatGateway ") == "AWS::EC2::NatGateway"


def test_already_canonical_and_unknown_types_pass_through():
    assert canonical_type("AWS::EC2::Instance") == "AWS::EC2::Instance"
    assert canonical_type("ecs:task-definition") == "ecs:task-definition"
    assert canonical_type("") == ""


def test_every_aws_registry_type_is_reachable_from_some_native_type():
    from adapters.aws.type_map import NATIVE_TO_CANONICAL

    reachable = set(NATIVE_TO_CANONICAL.values())
    missing = [
        t.type_id
        for t in get_registry().all_for_cloud("aws")
        if t.type_id not in reachable
    ]
    assert missing == []


def test_parse_resource_normalises_but_keeps_the_native_type():
    raw = {
        "Arn": "arn:aws:ec2:us-east-1:1:natgateway/nat-1",
        "ResourceType": "ec2:natgateway",
        "Region": "us-east-1",
        "Properties": [],
    }

    resource = _parse_resource(raw)

    assert resource.resource_type == "AWS::EC2::NatGateway"
    assert resource.native_type == "ec2:natgateway"


class TestRealCustomerInventory:
    """The 101 real types from the customer's 1000-resource account."""

    types = json.loads((FIXTURE / "real_inventory_types.json").read_text())

    def test_registry_now_recognises_the_costly_core_types(self):
        recognised = {
            t: canonical_type(t)
            for t in self.types
            if get_registry().get(canonical_type(t)) is not None
        }
        for t in (
            "ec2:instance",
            "ec2:natgateway",
            "ec2:volume",
            "rds:db",
            "rds:cluster",
            "lambda:function",
            "dynamodb:table",
            "s3:bucket",
            "ecs:service",
            "elasticache:cluster",
            "elasticloadbalancing:loadbalancer/app",
            "route53:hostedzone",
            "cloudfront:distribution",
        ):
            assert t in recognised, t

    def test_free_configuration_objects_are_no_longer_analysed(self):
        for t in (
            "ecs:task-definition",
            "ec2:security-group-rule",
            "ec2:security-group",
            "ec2:subnet",
            "ec2:route-table",
            "iam:role",
            "iam:policy",
            "memorydb:parametergroup",
            "rds:pg",
            "ec2:key-pair",
        ):
            assert is_config_only(t), t
            assert not _is_billable(t), t

    def test_cost_bearing_types_are_kept(self):
        for t in (
            "ec2:instance",
            "ec2:volume",
            "ec2:snapshot",
            "ec2:elastic-ip",
            "ec2:natgateway",
            "ec2:vpc-endpoint",
            "ec2:transit-gateway-attachment",
            "ec2:client-vpn-endpoint",
            "rds:db",
            "rds:snapshot",
            "secretsmanager:secret",
            "logs:log-group",
            "ecr:repository",
            "s3:bucket",
            "kms:key",
            "wafv2:webacl",
            "route53:hostedzone",
        ):
            assert _is_billable(t), t

    def test_most_of_the_noise_in_the_real_inventory_is_filtered(self):
        kept = sum(n for t, n in self.types.items() if _is_billable(t))
        total = sum(self.types.values())
        assert kept < total * 0.55, (kept, total)
        assert kept > 150  # and the cost-bearing resources are still there
