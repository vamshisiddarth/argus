from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import monitoring_v3
from google.api_core.exceptions import GoogleAPICallError
from google.protobuf.timestamp_pb2 import Timestamp

from adapters.base import MetricSummary

logger = logging.getLogger(__name__)

# (MetricType, Stat, label_key_for_resource_filter)
# Stat: "mean" for utilisation, "sum" for throughput/count.
# label_key: the monitored-resource label used to filter to this specific resource.
_METRICS: dict[str, list[tuple[str, str]]] = {
    "compute.googleapis.com/Instance": [
        ("compute.googleapis.com/instance/cpu/utilization", "mean"),
        ("compute.googleapis.com/instance/network/sent_bytes_count", "sum"),
        ("compute.googleapis.com/instance/network/received_bytes_count", "sum"),
    ],
    "compute.googleapis.com/Disk": [
        ("compute.googleapis.com/instance/disk/read_ops_count", "sum"),
        ("compute.googleapis.com/instance/disk/write_ops_count", "sum"),
    ],
    "sql.googleapis.com/Instance": [
        ("cloudsql.googleapis.com/database/cpu/utilization", "mean"),
        ("cloudsql.googleapis.com/database/network/connections", "mean"),
        ("cloudsql.googleapis.com/database/network/received_bytes_count", "sum"),
    ],
    "container.googleapis.com/Cluster": [
        ("kubernetes.io/container/cpu/request_utilization", "mean"),
        ("kubernetes.io/container/memory/request_utilization", "mean"),
        ("kubernetes.io/node/cpu/allocatable_utilization", "mean"),
    ],
    "run.googleapis.com/Service": [
        ("run.googleapis.com/request_count", "sum"),
        ("run.googleapis.com/request_latencies", "mean"),
        ("run.googleapis.com/container/cpu/utilizations", "mean"),
    ],
    "cloudfunctions.googleapis.com/Function": [
        ("cloudfunctions.googleapis.com/function/execution_count", "sum"),
        ("cloudfunctions.googleapis.com/function/execution_times", "mean"),
    ],
    "storage.googleapis.com/Bucket": [
        ("storage.googleapis.com/api/request_count", "sum"),
        ("storage.googleapis.com/network/sent_bytes_count", "sum"),
    ],
    "bigquery.googleapis.com/Dataset": [
        ("bigquery.googleapis.com/storage/table_count", "mean"),
        ("bigquery.googleapis.com/storage/stored_bytes", "mean"),
    ],
    "bigquery.googleapis.com/Table": [
        ("bigquery.googleapis.com/storage/stored_bytes", "mean"),
        ("bigquery.googleapis.com/storage/row_count", "mean"),
    ],
    "redis.googleapis.com/Instance": [
        ("redis.googleapis.com/clients/connected", "mean"),
        ("redis.googleapis.com/stats/cache_hit_ratio", "mean"),
        ("redis.googleapis.com/stats/memory/usage_ratio", "mean"),
    ],
    "spanner.googleapis.com/Instance": [
        ("spanner.googleapis.com/instance/cpu/utilization", "mean"),
        ("spanner.googleapis.com/instance/session_count", "mean"),
    ],
    "pubsub.googleapis.com/Topic": [
        ("pubsub.googleapis.com/topic/send_message_operation_count", "sum"),
        ("pubsub.googleapis.com/topic/byte_cost", "sum"),
    ],
    "pubsub.googleapis.com/Subscription": [
        ("pubsub.googleapis.com/subscription/pull_message_operation_count", "sum"),
        ("pubsub.googleapis.com/subscription/num_undelivered_messages", "mean"),
    ],
    "dataflow.googleapis.com/Job": [
        ("dataflow.googleapis.com/job/data_watermark_age", "mean"),
        ("dataflow.googleapis.com/job/elapsed_time", "mean"),
        ("dataflow.googleapis.com/job/element_count", "sum"),
    ],
    "dataproc.googleapis.com/Cluster": [
        ("dataproc.googleapis.com/cluster/yarn/allocated_memory_percentage", "mean"),
        ("dataproc.googleapis.com/cluster/hdfs/storage_utilization", "mean"),
    ],
    "aiplatform.googleapis.com/Endpoint": [
        ("aiplatform.googleapis.com/prediction/online/request_count", "sum"),
        ("aiplatform.googleapis.com/prediction/online/latencies", "mean"),
    ],
}

_PERIOD_SECONDS = 86400  # daily granularity
_FALLBACK_METRIC_LIMIT = 5


def get_metrics(
    project_id: str,
    resource_id: str,
    resource_type: str,
    days: int = 90,
) -> MetricSummary:
    """
    Fetch Cloud Monitoring metrics for a GCP resource.
    Falls back to listing available metrics for unknown resource types.
    """
    metric_defs = _METRICS.get(resource_type)
    if not metric_defs:
        metric_defs = _discover_metrics(project_id, resource_id, resource_type)
    if not metric_defs:
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={},
            has_data=False,
        )

    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=days)

    interval = monitoring_v3.TimeInterval(
        start_time=_to_proto_timestamp(start_time),
        end_time=_to_proto_timestamp(end_time),
    )
    aggregation = monitoring_v3.Aggregation(
        alignment_period={"seconds": _PERIOD_SECONDS},
        cross_series_reducer=monitoring_v3.Aggregation.Reducer.REDUCE_MEAN,
        per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
    )

    resource_filter = _resource_filter(resource_id, resource_type)
    metrics: dict[str, Any] = {}
    has_data = False

    for metric_type, stat in metric_defs:
        filter_str = f'metric.type="{metric_type}"'
        if resource_filter:
            filter_str += f" AND {resource_filter}"

        request = monitoring_v3.ListTimeSeriesRequest(
            name=project_name,
            filter=filter_str,
            interval=interval,
            aggregation=aggregation,
        )

        try:
            series = list(client.list_time_series(request=request))
        except GoogleAPICallError as exc:
            logger.warning(
                "cloud_monitoring_failed",
                extra={
                    "resource_id": resource_id,
                    "metric": metric_type,
                    "error": str(exc),
                },
            )
            metrics[metric_type] = None
            continue

        values: list[float] = [
            point.value.double_value or point.value.int64_value
            for ts in series
            for point in ts.points
        ]

        if not values:
            metrics[metric_type] = None
            continue

        has_data = True
        metrics[metric_type] = round(
            sum(values) / len(values) if stat == "mean" else sum(values), 4
        )

    return MetricSummary(
        resource_id=resource_id,
        resource_type=resource_type,
        period_days=days,
        metrics=metrics,
        has_data=has_data,
    )


def _discover_metrics(
    project_id: str,
    resource_id: str,
    resource_type: str,
) -> list[tuple[str, str]]:
    """Auto-discover available metrics for unknown resource types."""
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"

    # Derive a Cloud Monitoring monitored resource type prefix from the asset type.
    # e.g. "compute.googleapis.com/SomeNewThing" -> filter on "compute.googleapis.com"
    service_prefix = (
        resource_type.split("/")[0] if "/" in resource_type else resource_type
    )

    request = monitoring_v3.ListMetricDescriptorsRequest(
        name=project_name,
        filter=f'metric.type=starts_with("{service_prefix}")',
    )

    discovered: list[tuple[str, str]] = []
    try:
        for descriptor in client.list_metric_descriptors(request=request):
            metric_type: str = descriptor.type
            stat = (
                "sum"
                if any(
                    kw in metric_type.lower()
                    for kw in ("count", "bytes", "requests", "operations")
                )
                else "mean"
            )
            discovered.append((metric_type, stat))
            if len(discovered) >= _FALLBACK_METRIC_LIMIT:
                break
    except GoogleAPICallError as exc:
        logger.warning(
            "cloud_monitoring_list_metrics_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )

    return discovered


def _resource_filter(resource_id: str, resource_type: str) -> str:
    """
    Build a Cloud Monitoring filter string to scope metrics to a specific resource.
    Resource IDs are full asset names: //compute.googleapis.com/projects/p/zones/z/instances/name
    """
    # Extract the short resource name from the full asset name.
    name = resource_id.rstrip("/").split("/")[-1]

    match resource_type:
        case "compute.googleapis.com/Instance":
            return f'resource.labels.instance_id="{name}"'
        case "sql.googleapis.com/Instance":
            return f'resource.labels.database_id="{name}"'
        case "container.googleapis.com/Cluster":
            return f'resource.labels.cluster_name="{name}"'
        case "run.googleapis.com/Service":
            return f'resource.labels.service_name="{name}"'
        case "cloudfunctions.googleapis.com/Function":
            return f'resource.labels.function_name="{name}"'
        case "storage.googleapis.com/Bucket":
            return f'resource.labels.bucket_name="{name}"'
        case "pubsub.googleapis.com/Topic":
            return f'resource.labels.topic_id="{name}"'
        case "pubsub.googleapis.com/Subscription":
            return f'resource.labels.subscription_id="{name}"'
        case "redis.googleapis.com/Instance":
            return f'resource.labels.instance_id="{name}"'
        case "spanner.googleapis.com/Instance":
            return f'resource.labels.instance_id="{name}"'
        case "dataflow.googleapis.com/Job":
            return f'resource.labels.job_id="{name}"'
        case "dataproc.googleapis.com/Cluster":
            return f'resource.labels.cluster_name="{name}"'
        case "aiplatform.googleapis.com/Endpoint":
            return f'resource.labels.endpoint_id="{name}"'
    return ""


def _to_proto_timestamp(dt: datetime) -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(dt)
    return ts
