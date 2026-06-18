from __future__ import annotations

import logging
import os as _os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from adapters.base import MetricSummary

logger = logging.getLogger(__name__)

# (MetricName, Namespace, Stat, CloudWatch Dimension Key)
# Stat is "Average" for utilisation metrics, "Sum" for throughput/count metrics.
_METRICS: dict[str, list[tuple[str, str, str, str]]] = {
    "AWS::EC2::Instance": [
        ("CPUUtilization", "AWS/EC2", "Average", "InstanceId"),
        ("NetworkOut", "AWS/EC2", "Sum", "InstanceId"),
        ("NetworkIn", "AWS/EC2", "Sum", "InstanceId"),
    ],
    "AWS::RDS::DBInstance": [
        ("CPUUtilization", "AWS/RDS", "Average", "DBInstanceIdentifier"),
        ("DatabaseConnections", "AWS/RDS", "Average", "DBInstanceIdentifier"),
        ("NetworkReceiveThroughput", "AWS/RDS", "Sum", "DBInstanceIdentifier"),
    ],
    "AWS::EC2::NatGateway": [
        ("BytesOutToDestination", "AWS/NatGateway", "Sum", "NatGatewayId"),
        ("BytesInFromDestination", "AWS/NatGateway", "Sum", "NatGatewayId"),
        ("PacketsOutToDestination", "AWS/NatGateway", "Sum", "NatGatewayId"),
    ],
    "AWS::ElasticLoadBalancingV2::LoadBalancer": [
        ("RequestCount", "AWS/ApplicationELB", "Sum", "LoadBalancer"),
        ("ActiveConnectionCount", "AWS/ApplicationELB", "Sum", "LoadBalancer"),
        ("TargetResponseTime", "AWS/ApplicationELB", "Average", "LoadBalancer"),
    ],
    "AWS::ElasticLoadBalancing::LoadBalancer": [
        ("RequestCount", "AWS/ELB", "Sum", "LoadBalancerName"),
        ("HealthyHostCount", "AWS/ELB", "Average", "LoadBalancerName"),
        ("UnHealthyHostCount", "AWS/ELB", "Average", "LoadBalancerName"),
    ],
    "AWS::Lambda::Function": [
        ("Invocations", "AWS/Lambda", "Sum", "FunctionName"),
        ("Duration", "AWS/Lambda", "Average", "FunctionName"),
        ("Errors", "AWS/Lambda", "Sum", "FunctionName"),
    ],
    "AWS::EC2::Volume": [
        ("VolumeReadOps", "AWS/EBS", "Sum", "VolumeId"),
        ("VolumeWriteOps", "AWS/EBS", "Sum", "VolumeId"),
        ("VolumeReadBytes", "AWS/EBS", "Sum", "VolumeId"),
    ],
    "AWS::DynamoDB::Table": [
        ("ConsumedReadCapacityUnits", "AWS/DynamoDB", "Sum", "TableName"),
        ("ConsumedWriteCapacityUnits", "AWS/DynamoDB", "Sum", "TableName"),
        ("SuccessfulRequestLatency", "AWS/DynamoDB", "Average", "TableName"),
    ],
    "AWS::SQS::Queue": [
        ("NumberOfMessagesSent", "AWS/SQS", "Sum", "QueueName"),
        ("NumberOfMessagesReceived", "AWS/SQS", "Sum", "QueueName"),
        ("ApproximateNumberOfMessagesVisible", "AWS/SQS", "Average", "QueueName"),
    ],
    "AWS::ElastiCache::CacheCluster": [
        ("CPUUtilization", "AWS/ElastiCache", "Average", "CacheClusterId"),
        ("CurrConnections", "AWS/ElastiCache", "Average", "CacheClusterId"),
        ("CacheHits", "AWS/ElastiCache", "Sum", "CacheClusterId"),
    ],
    "AWS::Redshift::Cluster": [
        ("CPUUtilization", "AWS/Redshift", "Average", "ClusterIdentifier"),
        ("DatabaseConnections", "AWS/Redshift", "Average", "ClusterIdentifier"),
        ("ReadIOPS", "AWS/Redshift", "Average", "ClusterIdentifier"),
    ],
    "AWS::OpenSearchService::Domain": [
        ("CPUUtilization", "AWS/ES", "Average", "DomainName"),
        ("SearchableDocuments", "AWS/ES", "Average", "DomainName"),
        ("IndexingRate", "AWS/ES", "Average", "DomainName"),
    ],
    "AWS::ECS::Service": [
        ("CPUUtilization", "AWS/ECS", "Average", "ServiceName"),
        ("MemoryUtilization", "AWS/ECS", "Average", "ServiceName"),
    ],
    "AWS::EKS::Cluster": [
        # Requires Container Insights enabled on the cluster.
        ("cluster_node_count", "ContainerInsights", "Average", "ClusterName"),
        ("node_cpu_utilization", "ContainerInsights", "Average", "ClusterName"),
        ("node_memory_utilization", "ContainerInsights", "Average", "ClusterName"),
    ],
    "AWS::Kinesis::Stream": [
        ("GetRecords.Records", "AWS/Kinesis", "Sum", "StreamName"),
        ("IncomingRecords", "AWS/Kinesis", "Sum", "StreamName"),
        ("PutRecord.Success", "AWS/Kinesis", "Sum", "StreamName"),
    ],
    "AWS::SNS::Topic": [
        ("NumberOfNotificationsDelivered", "AWS/SNS", "Sum", "TopicName"),
        ("NumberOfMessagesPublished", "AWS/SNS", "Sum", "TopicName"),
        ("NumberOfNotificationsFailed", "AWS/SNS", "Sum", "TopicName"),
    ],
    "AWS::ApiGateway::RestApi": [
        ("Count", "AWS/ApiGateway", "Sum", "ApiName"),
        ("4XXError", "AWS/ApiGateway", "Sum", "ApiName"),
        ("5XXError", "AWS/ApiGateway", "Sum", "ApiName"),
    ],
    "AWS::ApiGateway::Stage": [
        ("Count", "AWS/ApiGateway", "Sum", "Stage"),
        ("4XXError", "AWS/ApiGateway", "Sum", "Stage"),
        ("Latency", "AWS/ApiGateway", "Average", "Stage"),
    ],
    "AWS::CloudFront::Distribution": [
        ("Requests", "AWS/CloudFront", "Sum", "DistributionId"),
        ("BytesDownloaded", "AWS/CloudFront", "Sum", "DistributionId"),
        ("4xxErrorRate", "AWS/CloudFront", "Average", "DistributionId"),
    ],
    "AWS::StepFunctions::StateMachine": [
        ("ExecutionsStarted", "AWS/States", "Sum", "StateMachineArn"),
        ("ExecutionsSucceeded", "AWS/States", "Sum", "StateMachineArn"),
        ("ExecutionsFailed", "AWS/States", "Sum", "StateMachineArn"),
    ],
    "AWS::Glue::Job": [
        ("glue.driver.aggregate.bytesRead", "Glue", "Sum", "JobName"),
        ("glue.driver.aggregate.elapsedTime", "Glue", "Average", "JobName"),
    ],
    "AWS::MSK::Cluster": [
        ("BytesInPerSec", "AWS/Kafka", "Sum", "Cluster Name"),
        ("BytesOutPerSec", "AWS/Kafka", "Sum", "Cluster Name"),
        ("KafkaDataLogsDiskUsed", "AWS/Kafka", "Average", "Cluster Name"),
    ],
    "AWS::SageMaker::Endpoint": [
        ("Invocations", "AWS/SageMaker", "Sum", "EndpointName"),
        ("ModelLatency", "AWS/SageMaker", "Average", "EndpointName"),
        ("CPUUtilization", "AWS/SageMaker", "Average", "EndpointName"),
    ],
    # ── Aurora / RDS Cluster ──────────────────────────────────────────────────
    "AWS::RDS::DBCluster": [
        ("CPUUtilization", "AWS/RDS", "Average", "DBClusterIdentifier"),
        ("DatabaseConnections", "AWS/RDS", "Average", "DBClusterIdentifier"),
        ("AuroraReplicaLag", "AWS/RDS", "Average", "DBClusterIdentifier"),
    ],
    # ── ElastiCache Replication Group ─────────────────────────────────────────
    "AWS::ElastiCache::ReplicationGroup": [
        ("CurrConnections", "AWS/ElastiCache", "Average", "ReplicationGroupId"),
        ("CacheHitRate", "AWS/ElastiCache", "Average", "ReplicationGroupId"),
        ("ReplicationLag", "AWS/ElastiCache", "Average", "ReplicationGroupId"),
    ],
    # ── EMR Cluster ───────────────────────────────────────────────────────────
    "AWS::EMR::Cluster": [
        (
            "YARNMemoryAvailablePercentage",
            "AWS/ElasticMapReduce",
            "Average",
            "JobFlowId",
        ),
        ("ContainerPendingRatio", "AWS/ElasticMapReduce", "Average", "JobFlowId"),
        ("AppsRunning", "AWS/ElasticMapReduce", "Average", "JobFlowId"),
    ],
    # ── DMS Replication Instance ──────────────────────────────────────────────
    "AWS::DMS::ReplicationInstance": [
        ("CPUUtilization", "AWS/DMS", "Average", "ReplicationInstanceIdentifier"),
        ("FreeableMemory", "AWS/DMS", "Average", "ReplicationInstanceIdentifier"),
        ("CDCLatencySource", "AWS/DMS", "Average", "ReplicationInstanceIdentifier"),
    ],
    # ── Neptune Cluster ───────────────────────────────────────────────────────
    "AWS::Neptune::DBCluster": [
        ("CPUUtilization", "AWS/Neptune", "Average", "DBClusterIdentifier"),
        ("DatabaseConnections", "AWS/Neptune", "Average", "DBClusterIdentifier"),
        ("BufferCacheHitRatio", "AWS/Neptune", "Average", "DBClusterIdentifier"),
    ],
    # ── DocumentDB Cluster ────────────────────────────────────────────────────
    "AWS::DocDB::DBCluster": [
        ("CPUUtilization", "AWS/DocDB", "Average", "DBClusterIdentifier"),
        ("DatabaseConnections", "AWS/DocDB", "Average", "DBClusterIdentifier"),
        ("BufferCacheHitRatio", "AWS/DocDB", "Average", "DBClusterIdentifier"),
    ],
    # ── WorkSpaces ────────────────────────────────────────────────────────────
    "AWS::WorkSpaces::Workspace": [
        ("Available", "AWS/WorkSpaces", "Average", "WorkspaceId"),
        ("InSessionLatency", "AWS/WorkSpaces", "Average", "WorkspaceId"),
        ("SessionLaunchTime", "AWS/WorkSpaces", "Average", "WorkspaceId"),
    ],
    # ── Kinesis Firehose ──────────────────────────────────────────────────────
    "AWS::KinesisFirehose::DeliveryStream": [
        ("IncomingBytes", "AWS/Firehose", "Sum", "DeliveryStreamName"),
        ("IncomingRecords", "AWS/Firehose", "Sum", "DeliveryStreamName"),
        ("DeliveryToS3.Success", "AWS/Firehose", "Sum", "DeliveryStreamName"),
    ],
    # ── AppSync GraphQL API ───────────────────────────────────────────────────
    "AWS::AppSync::GraphQLApi": [
        ("4XXError", "AWS/AppSync", "Sum", "GraphQLAPIId"),
        ("5XXError", "AWS/AppSync", "Sum", "GraphQLAPIId"),
        ("Latency", "AWS/AppSync", "Average", "GraphQLAPIId"),
    ],
    # ── EventBridge Rule ──────────────────────────────────────────────────────
    "AWS::Events::Rule": [
        ("TriggeredRules", "AWS/Events", "Sum", "RuleName"),
        ("Invocations", "AWS/Events", "Sum", "RuleName"),
        ("FailedInvocations", "AWS/Events", "Sum", "RuleName"),
    ],
    # ── Elastic Beanstalk Environment ─────────────────────────────────────────
    "AWS::ElasticBeanstalk::Environment": [
        ("EnvironmentHealth", "AWS/ElasticBeanstalk", "Average", "EnvironmentName"),
        ("ApplicationRequestsTotal", "AWS/ElasticBeanstalk", "Sum", "EnvironmentName"),
        ("CPUUtilization", "AWS/ElasticBeanstalk", "Average", "EnvironmentName"),
    ],
    # ── CodeBuild Project ─────────────────────────────────────────────────────
    "AWS::CodeBuild::Project": [
        ("Builds", "AWS/CodeBuild", "Sum", "ProjectName"),
        ("SucceededBuilds", "AWS/CodeBuild", "Sum", "ProjectName"),
        ("Duration", "AWS/CodeBuild", "Average", "ProjectName"),
    ],
    # ── Transfer Family Server ────────────────────────────────────────────────
    "AWS::Transfer::Server": [
        ("FilesIn", "AWS/Transfer", "Sum", "ServerId"),
        ("FilesOut", "AWS/Transfer", "Sum", "ServerId"),
        ("BytesIn", "AWS/Transfer", "Sum", "ServerId"),
    ],
    # ── WAFv2 WebACL ──────────────────────────────────────────────────────────
    "AWS::WAFv2::WebACL": [
        ("AllowedRequests", "AWS/WAFV2", "Sum", "WebACL"),
        ("BlockedRequests", "AWS/WAFV2", "Sum", "WebACL"),
        ("CountedRequests", "AWS/WAFV2", "Sum", "WebACL"),
    ],
    # ── S3 Bucket (requires per-bucket request metrics enabled) ───────────────
    "AWS::S3::Bucket": [
        ("NumberOfObjects", "AWS/S3", "Average", "BucketName"),
        ("BucketSizeBytes", "AWS/S3", "Average", "BucketName"),
        ("AllRequests", "AWS/S3", "Sum", "BucketName"),
    ],
    # ── Cognito User Pool ─────────────────────────────────────────────────────
    "AWS::Cognito::UserPool": [
        ("SignInSuccesses", "AWS/Cognito", "Sum", "UserPool"),
        ("TokenRefreshSuccesses", "AWS/Cognito", "Sum", "UserPool"),
        ("SignUpSuccesses", "AWS/Cognito", "Sum", "UserPool"),
    ],
    # ── IoT Core ──────────────────────────────────────────────────────────────
    "AWS::IoT::Thing": [
        ("PublishIn.Success", "AWS/IoT", "Sum", "Protocol"),
        ("PublishOut.Success", "AWS/IoT", "Sum", "Protocol"),
        ("Connect.Success", "AWS/IoT", "Sum", "Protocol"),
    ],
    # ── MediaLive Channel ─────────────────────────────────────────────────────
    "AWS::MediaLive::Channel": [
        ("ActiveOutputs", "AWS/MediaLive", "Average", "ChannelId"),
        ("DroppedFrames", "AWS/MediaLive", "Sum", "ChannelId"),
        ("NetworkIn", "AWS/MediaLive", "Sum", "ChannelId"),
    ],
    # ── Batch Job Queue ───────────────────────────────────────────────────────
    "AWS::Batch::JobQueue": [
        ("PendingJobCount", "AWS/Batch", "Average", "JobQueueName"),
        ("RunnableJobCount", "AWS/Batch", "Average", "JobQueueName"),
        ("RunningJobCount", "AWS/Batch", "Average", "JobQueueName"),
    ],
    # ── Route 53 Hosted Zone ──────────────────────────────────────────────────
    "AWS::Route53::HostedZone": [
        ("DNSQueries", "AWS/Route53", "Sum", "HostedZoneId"),
    ],
}

_PERIOD_SECONDS = 86400  # daily granularity — one data point per day

# Default lookback for metric queries. 90 days covers quarterly usage patterns and
# aligns with the CloudTrail lookback window so both signals share the same horizon.
# At daily granularity CloudWatch retains data for 455 days, so 90 days is safe.
# Override via METRICS_LOOKBACK_DAYS env var (e.g. 14 for faster/cheaper dev runs).
DEFAULT_METRICS_DAYS: int = int(_os.environ.get("METRICS_LOOKBACK_DAYS", "90"))


def get_metrics(
    session: boto3.Session,
    resource_id: str,
    resource_type: str,
    days: int = DEFAULT_METRICS_DAYS,
) -> MetricSummary:
    """
    Fetch usage metrics for a resource using CloudWatch GetMetricData (batched).
    Returns a MetricSummary with averaged/summed values over the period.
    For resource types without a hand-coded _METRICS entry, falls back to
    auto-discovery via ListMetrics so the AI still gets signal data.

    Also injects instance size details (instance_type, memory_mb, vcpus) into
    the metrics dict for resource types where right-sizing is actionable. This
    gives the AI the current instance size so it can recommend a specific
    smaller tier rather than a generic "consider downsizing".
    """
    metric_defs = _METRICS.get(resource_type)
    if not metric_defs:
        metric_defs = _discover_metrics(session, resource_id, resource_type)
    if not metric_defs:
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={},
            has_data=False,
        )

    region = _region_from_arn(resource_id)
    dim_value = _dimension_value(resource_id, resource_type)
    client = session.client("cloudwatch", region_name=region)

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=days)

    queries: list[Any] = [
        {
            "Id": f"m{i}",
            "MetricStat": {
                "Metric": {
                    "Namespace": namespace,
                    "MetricName": metric_name,
                    "Dimensions": [{"Name": dim_key, "Value": dim_value}],
                },
                "Period": _PERIOD_SECONDS,
                "Stat": stat,
            },
            "ReturnData": True,
        }
        for i, (metric_name, namespace, stat, dim_key) in enumerate(metric_defs)
    ]

    try:
        response = client.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start_time,
            EndTime=end_time,
        )
    except ClientError as exc:
        logger.warning(
            "cloudwatch_get_metric_data_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={},
            has_data=False,
        )

    summary = _parse_results(
        results=response.get("MetricDataResults", []),
        metric_defs=metric_defs,
        resource_id=resource_id,
        resource_type=resource_type,
        days=days,
    )

    # Best-effort: inject current instance size so AI can recommend a specific
    # right-sizing target rather than a generic "consider downsizing".
    _enrich_instance_details(session, resource_id, resource_type, summary.metrics)

    return summary


def _enrich_instance_details(
    session: boto3.Session,
    resource_id: str,
    resource_type: str,
    metrics: dict[str, Any],
) -> None:
    """
    Inject current instance size metadata into the metrics dict (in-place).

    This enriches the AI's context so it can recommend a *specific* right-sizing
    target (e.g. "downsize from db.r5.4xlarge → db.r5.xlarge") rather than a
    vague "consider downsizing". Failures are silently ignored — metrics are
    still valid without this data.

    Adds keys such as:
      instance_type    — e.g. "t3.medium", "db.r5.4xlarge", "cache.m6g.large"
      memory_mb        — Lambda allocated memory in MB
      vcpus            — EC2 vCPU count (from InstanceType metadata)
      node_type        — Redshift node type
      instance_count   — Redshift / OpenSearch cluster node count
    """
    region = _region_from_arn(resource_id)
    resp: Any  # declared here so mypy doesn't infer a narrow type from first assignment
    try:
        match resource_type:
            case "AWS::EC2::Instance":
                ec2 = session.client("ec2", region_name=region)
                instance_id = resource_id.split("/")[-1].split(":")[-1]
                resp = ec2.describe_instances(InstanceIds=[instance_id])
                reservations = resp.get("Reservations", [])
                if reservations:
                    inst = reservations[0]["Instances"][0]
                    metrics["instance_type"] = inst.get("InstanceType")
                    # vCPU count helps the AI understand the scale of the machine
                    cpu_opts = inst.get("CpuOptions", {})
                    if cpu_opts:
                        metrics["vcpus"] = cpu_opts.get("CoreCount", 1) * cpu_opts.get(
                            "ThreadsPerCore", 1
                        )

            case "AWS::RDS::DBInstance":
                rds = session.client("rds", region_name=region)
                db_id = resource_id.split(":")[-1]
                resp = rds.describe_db_instances(DBInstanceIdentifier=db_id)
                instances = resp.get("DBInstances", [])
                if instances:
                    db = instances[0]
                    metrics["instance_type"] = db.get("DBInstanceClass")
                    metrics["engine"] = (
                        f"{db.get('Engine')} {db.get('EngineVersion', '')}".strip()
                    )
                    metrics["storage_gb"] = db.get("AllocatedStorage")
                    metrics["multi_az"] = db.get("MultiAZ", False)

            case "AWS::RDS::DBCluster":
                rds = session.client("rds", region_name=region)
                cluster_id = resource_id.split(":")[-1]
                resp = rds.describe_db_clusters(DBClusterIdentifier=cluster_id)
                clusters = resp.get("DBClusters", [])
                if clusters:
                    cluster = clusters[0]
                    engine = cluster.get("Engine", "")
                    version = cluster.get("EngineVersion", "")
                    metrics["engine"] = f"{engine} {version}".strip()
                    metrics["instance_count"] = len(cluster.get("DBClusterMembers", []))
                    # Fetch instance class from the writer instance
                    members = cluster.get("DBClusterMembers", [])
                    writer = next(
                        (m for m in members if m.get("IsClusterWriter")), None
                    )
                    if writer:
                        inst_resp = rds.describe_db_instances(
                            DBInstanceIdentifier=writer["DBInstanceIdentifier"]
                        )
                        inst_list = inst_resp.get("DBInstances", [])
                        if inst_list:
                            metrics["instance_type"] = inst_list[0].get(
                                "DBInstanceClass"
                            )

            case "AWS::ElastiCache::CacheCluster":
                ec = session.client("elasticache", region_name=region)
                cluster_id = resource_id.split(":")[-1]
                resp = ec.describe_cache_clusters(CacheClusterId=cluster_id)
                clusters = resp.get("CacheClusters", [])
                if clusters:
                    c = clusters[0]
                    metrics["instance_type"] = c.get("CacheNodeType")
                    metrics["num_cache_nodes"] = c.get("NumCacheNodes")
                    metrics["engine"] = (
                        f"{c.get('Engine')} {c.get('EngineVersion', '')}".strip()
                    )

            case "AWS::ElastiCache::ReplicationGroup":
                ec = session.client("elasticache", region_name=region)
                rg_id = resource_id.split(":")[-1]
                resp = ec.describe_replication_groups(ReplicationGroupId=rg_id)
                groups = resp.get("ReplicationGroups", [])
                if groups:
                    rg = groups[0]
                    metrics["instance_type"] = rg.get("CacheNodeType")
                    metrics["node_count"] = sum(
                        len(ng.get("NodeGroupMembers", []))
                        for ng in rg.get("NodeGroups", [])
                    )

            case "AWS::Redshift::Cluster":
                rs = session.client("redshift", region_name=region)
                cluster_id = resource_id.split(":")[-1]
                resp = rs.describe_clusters(ClusterIdentifier=cluster_id)
                clusters = resp.get("Clusters", [])
                if clusters:
                    c = clusters[0]
                    metrics["instance_type"] = c.get("NodeType")
                    metrics["instance_count"] = c.get("NumberOfNodes")

            case "AWS::OpenSearchService::Domain":
                oss = session.client("opensearch", region_name=region)
                domain_name = resource_id.split("/")[-1]
                resp = oss.describe_domain(DomainName=domain_name)
                config = resp.get("DomainStatus", {}).get("ClusterConfig", {})
                if config:
                    metrics["instance_type"] = config.get("InstanceType")
                    metrics["instance_count"] = config.get("InstanceCount")
                    metrics["dedicated_master"] = config.get(
                        "DedicatedMasterEnabled", False
                    )

            case "AWS::Lambda::Function":
                lam = session.client("lambda", region_name=region)
                func_name = resource_id.split(":")[-1]
                resp = lam.get_function_configuration(FunctionName=func_name)
                metrics["memory_mb"] = resp.get("MemorySize")
                metrics["ephemeral_storage_mb"] = resp.get("EphemeralStorage", {}).get(
                    "Size"
                )
                metrics["runtime"] = resp.get("Runtime")

            case "AWS::DMS::ReplicationInstance":
                dms = session.client("dms", region_name=region)
                # DMS uses the ARN as the filter
                resp = dms.describe_replication_instances(
                    Filters=[
                        {"Name": "replication-instance-arn", "Values": [resource_id]}
                    ]
                )
                instances = resp.get("ReplicationInstances", [])
                if instances:
                    metrics["instance_type"] = instances[0].get(
                        "ReplicationInstanceClass"
                    )
                    metrics["storage_gb"] = instances[0].get("AllocatedStorage")

    except ClientError as exc:
        # Best-effort — missing size data doesn't invalidate the metrics
        logger.debug(
            "instance_details_fetch_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "instance_details_unexpected_error",
            extra={"resource_id": resource_id, "error": str(exc)},
        )


def _parse_results(
    results: list[Any],
    metric_defs: list[tuple[str, str, str, str]],
    resource_id: str,
    resource_type: str,
    days: int,
) -> MetricSummary:
    metrics: dict[str, Any] = {}
    has_data = False

    for result, (metric_name, _, stat, _) in zip(results, metric_defs, strict=False):
        values: list[float] = result.get("Values", [])
        if not values:
            metrics[metric_name] = None
            continue
        has_data = True
        if stat == "Average":
            metrics[metric_name] = round(sum(values) / len(values), 4)
        else:
            metrics[metric_name] = round(sum(values), 2)

    return MetricSummary(
        resource_id=resource_id,
        resource_type=resource_type,
        period_days=days,
        metrics=metrics,
        has_data=has_data,
    )


_FALLBACK_METRIC_LIMIT = 5  # max metrics to auto-discover per unknown resource


def _discover_metrics(
    session: boto3.Session,
    resource_id: str,
    resource_type: str,
) -> list[tuple[str, str, str, str]]:
    """
    For resource types not in _METRICS, ask CloudWatch what metrics exist
    for this resource and return up to _FALLBACK_METRIC_LIMIT definitions.
    Uses the ARN as a dimension value where possible.
    """
    region = _region_from_arn(resource_id)
    client = session.client("cloudwatch", region_name=region)

    # Try to find metrics that reference this resource by ARN or last-segment name.
    dim_value = _dimension_value(resource_id, resource_type)
    discovered: list[tuple[str, str, str, str]] = []

    try:
        paginator = client.get_paginator("list_metrics")
        for page in paginator.paginate():
            for m in page.get("Metrics", []):
                for dim in m.get("Dimensions", []):
                    if dim.get("Value") in (resource_id, dim_value):
                        metric_name: str = m["MetricName"]
                        namespace: str = m["Namespace"]
                        dim_key: str = dim["Name"]
                        # Use Sum for count/bytes-sounding names, Average otherwise.
                        stat = (
                            "Sum"
                            if any(
                                kw in metric_name.lower()
                                for kw in (
                                    "count",
                                    "bytes",
                                    "records",
                                    "invocations",
                                    "requests",
                                )
                            )
                            else "Average"
                        )
                        discovered.append((metric_name, namespace, stat, dim_key))
                        if len(discovered) >= _FALLBACK_METRIC_LIMIT:
                            return discovered
    except ClientError as exc:
        logger.warning(
            "cloudwatch_list_metrics_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )

    return discovered


def _region_from_arn(arn: str) -> str:
    parts = arn.split(":")
    region = parts[3] if len(parts) > 3 else ""
    return region or "us-east-1"


def _dimension_value(arn: str, resource_type: str) -> str:
    """
    Extract the CloudWatch dimension value from an ARN.
    Most resources use the last segment; some (ALB, RDS, Lambda) need special handling.
    """
    parts = arn.split(":")
    resource_part = ":".join(parts[5:])

    match resource_type:
        case "AWS::ElasticLoadBalancingV2::LoadBalancer":
            # arn:...:loadbalancer/app/name/id -> app/name/id
            if "loadbalancer/" in resource_part:
                return resource_part.split("loadbalancer/", 1)[1]
        case "AWS::RDS::DBInstance" | "AWS::Lambda::Function" | "AWS::SNS::Topic":
            # arn:...:db:name or function:name or :topic-name
            return resource_part.split(":")[-1]
        case "AWS::SQS::Queue":
            # arn:aws:sqs:region:account:queue-name
            return resource_part  # queue name is the whole resource_part
        case "AWS::CloudFront::Distribution":
            # arn:aws:cloudfront::account:distribution/EDFDVBD6EXAMPLE
            return resource_part.split("/")[-1]
        case "AWS::StepFunctions::StateMachine":
            # dimension is the full ARN for Step Functions
            return arn
        case "AWS::MSK::Cluster":
            # arn:aws:kafka:region:account:cluster/name/uuid -> name
            if "cluster/" in resource_part:
                return resource_part.split("cluster/")[1].split("/")[0]
        case "AWS::SageMaker::Endpoint":
            # arn:aws:sagemaker:region:account:endpoint/name
            return resource_part.split("/")[-1]
        case "AWS::Glue::Job":
            # arn:aws:glue:region:account:job/name
            return resource_part.split("/")[-1]
        case (
            "AWS::RDS::DBCluster" | "AWS::Neptune::DBCluster" | "AWS::DocDB::DBCluster"
        ):
            # arn:...:cluster:name
            return resource_part.split(":")[-1]
        case "AWS::ElastiCache::ReplicationGroup":
            # arn:aws:elasticache:region:account:replicationgroup:name
            return resource_part.split(":")[-1]
        case "AWS::EMR::Cluster":
            # arn:aws:elasticmapreduce:region:account:cluster/j-XXXXXXXX
            return resource_part.split("/")[-1]
        case "AWS::DMS::ReplicationInstance":
            # arn:aws:dms:region:account:rep:name
            return resource_part.split(":")[-1]
        case "AWS::WorkSpaces::Workspace":
            # arn:aws:workspaces:region:account:workspace/ws-xxxxxxxx
            return resource_part.split("/")[-1]
        case "AWS::KinesisFirehose::DeliveryStream":
            # arn:aws:firehose:region:account:deliverystream/name
            return resource_part.split("/")[-1]
        case "AWS::AppSync::GraphQLApi":
            # arn:aws:appsync:region:account:apis/apiId
            return resource_part.split("/")[-1]
        case "AWS::Events::Rule":
            # arn:aws:events:region:account:rule/name
            return resource_part.split("/")[-1]
        case "AWS::ElasticBeanstalk::Environment":
            # arn:aws:elasticbeanstalk:region:account:environment/app/env
            return resource_part.split("/")[-1]
        case "AWS::CodeBuild::Project":
            # arn:aws:codebuild:region:account:project/name
            return resource_part.split("/")[-1]
        case "AWS::Transfer::Server":
            # arn:aws:transfer:region:account:server/s-xxxxxxxx
            return resource_part.split("/")[-1]
        case "AWS::WAFv2::WebACL":
            # arn:aws:wafv2:region:account:regional/webacl/name/id -> name
            parts_slash = resource_part.split("/")
            return parts_slash[-2] if len(parts_slash) >= 2 else parts_slash[-1]
        case "AWS::S3::Bucket":
            # arn:aws:s3:::bucket-name
            return resource_part
        case "AWS::Cognito::UserPool":
            # arn:aws:cognito-idp:region:account:userpool/us-east-1_XXXXXXX
            return resource_part.split("/")[-1]
        case "AWS::MediaLive::Channel":
            # arn:aws:medialive:region:account:channel:id
            return resource_part.split(":")[-1]
        case "AWS::Batch::JobQueue":
            # arn:aws:batch:region:account:job-queue/name
            return resource_part.split("/")[-1]
        case "AWS::Route53::HostedZone":
            # arn:aws:route53:::hostedzone/ZXXXXXXX
            return resource_part.split("/")[-1]

    if "/" in resource_part:
        return resource_part.split("/")[-1]
    if ":" in resource_part:
        return resource_part.split(":")[-1]
    return resource_part
