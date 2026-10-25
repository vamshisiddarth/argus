"""
Resource Explorer resource types vs Argus resource types.

Resource Explorer reports `service:type` ("ec2:natgateway"). Argus's registry,
CloudWatch metric table, baseline rules and remediation policies are keyed on
CloudFormation-style ids ("AWS::EC2::NatGateway"). This module joins them, and
also says which native types are free configuration objects that never need
analysis.
"""

from __future__ import annotations

from core.registry import get_registry

# Irregular names. Everything regular ("ec2:instance", "sqs:queue", ...) is derived
# from the registry below.
_ELBV2 = "AWS::ElasticLoadBalancingV2::LoadBalancer"

_OVERRIDES: dict[str, str] = {
    "rds:db": "AWS::RDS::DBInstance",
    "rds:cluster": "AWS::RDS::DBCluster",
    "elasticloadbalancing:loadbalancer": "AWS::ElasticLoadBalancing::LoadBalancer",
    "elasticloadbalancing:loadbalancer/app": _ELBV2,
    "elasticloadbalancing:loadbalancer/net": _ELBV2,
    "elasticloadbalancing:loadbalancer/gwy": _ELBV2,
    "elasticache:cluster": "AWS::ElastiCache::CacheCluster",
    "elasticache:replicationgroup": "AWS::ElastiCache::ReplicationGroup",
    "es:domain": "AWS::OpenSearchService::Domain",
    "kafka:cluster": "AWS::MSK::Cluster",
    "states:statemachine": "AWS::StepFunctions::StateMachine",
    "firehose:deliverystream": "AWS::KinesisFirehose::DeliveryStream",
    "elasticmapreduce:cluster": "AWS::EMR::Cluster",
    "dms:rep": "AWS::DMS::ReplicationInstance",
    "wafv2:regional/webacl": "AWS::WAFv2::WebACL",
    "wafv2:global/webacl": "AWS::WAFv2::WebACL",
    "cognito-idp:userpool": "AWS::Cognito::UserPool",
    "apigateway:restapis": "AWS::ApiGateway::RestApi",
    "apigateway:restapis/stages": "AWS::ApiGateway::Stage",
    "appsync:apis": "AWS::AppSync::GraphQLApi",
    "batch:job-queue": "AWS::Batch::JobQueue",
    "ec2:elastic-ip": "AWS::EC2::EIP",
}


def _derive_from_registry() -> dict[str, str]:
    derived: dict[str, str] = {}
    for spec in get_registry().all_for_cloud("aws"):
        parts = spec.type_id.split("::")
        if len(parts) == 3:
            derived[f"{parts[1]}:{parts[2]}".lower()] = spec.type_id
    return derived


NATIVE_TO_CANONICAL: dict[str, str] = {**_derive_from_registry(), **_OVERRIDES}


def canonical_type(native: str) -> str:
    """Registry id for a Resource Explorer type; unknown types pass through."""
    key = native.strip().lower()
    return NATIVE_TO_CANONICAL.get(key, native.strip())


# Free configuration objects: never on a bill, nothing to be "idle". Matching is by
# exact name, or by prefix for the entries ending in ":" or "-".
_CONFIG_ONLY_EXACT = frozenset(
    {
        "ecs:task-definition",
        "ec2:subnet",
        "ec2:route-table",
        "ec2:network-acl",
        "ec2:dhcp-options",
        "ec2:key-pair",
        "ec2:prefix-list",
        "ec2:internet-gateway",
        "ec2:vpc",
        "ec2:vpc-peering-connection",
        "ec2:vpc-flow-log",
        "ec2:launch-template",
        "ec2:network-interface",
        "ec2:network-insights-path",
        "ec2:network-insights-access-scope",
        "ec2:network-insights-analysis",
        "ec2:image",
        "ec2:transit-gateway",
        "ec2:transit-gateway-route-table",
        "ec2:reserved-instances",
        "ec2:placement-group",
        "rds:pg",
        "rds:cluster-pg",
        "rds:subgrp",
        "rds:og",
        "rds:es",
        "memorydb:parametergroup",
        "memorydb:acl",
        "memorydb:user",
        "memorydb:subnetgroup",
        "elasticache:user",
        "elasticache:usergroup",
        "elasticache:parametergroup",
        "elasticache:subnetgroup",
        "events:event-bus",
        "elasticloadbalancing:targetgroup",
        "elasticloadbalancing:listener-rule/app",
        "elasticloadbalancing:listener-rule/net",
        "elasticloadbalancing:listener/app",
        "elasticloadbalancing:listener/net",
        "lambda:function/version",
        "lambda:layer-version",
        "lambda:event-source-mapping",
        "elasticfilesystem:access-point",
        "athena:datacatalog",
        "athena:workgroup",
        "glue:database",
        "glue:table",
        "sagemaker:user-profile",
        "servicediscovery:service",
        "servicediscovery:namespace",
        "wafv2:ipset",
        "wafv2:regexpatternset",
        "ses:identity",
        "acm:certificate",
        "apprunner:autoscalingconfiguration",
        "cloudwatch:alarm",
        "cloudwatch:dashboard",
        "sns:subscription",
        "dms:endpoint",
        "dms:subgrp",
    }
)
_CONFIG_ONLY_PREFIXES = (
    "iam:",
    "cloudformation:",
    "ssm:",
    "resource-explorer-2:",
    "ec2:security-group",
    "xray:",
    "ce:",
    "config:",
    "guardduty:",
    "securityhub:",
    "organizations:",
    "access-analyzer:",
    "resource-groups:",
    "servicecatalog:",
)


def is_config_only(native_type: str) -> bool:
    key = native_type.strip().lower()
    return key in _CONFIG_ONLY_EXACT or key.startswith(_CONFIG_ONLY_PREFIXES)
