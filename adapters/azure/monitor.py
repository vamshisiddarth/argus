from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.monitor.query import MetricAggregationType, MetricsQueryClient

from adapters.base import MetricSummary

logger = logging.getLogger(__name__)

# (MetricName, AggregationType)
_METRICS: dict[str, list[tuple[str, str]]] = {
    # Virtual Machines
    "microsoft.compute/virtualmachines": [
        ("Percentage CPU", "Average"),
        ("Network In Total", "Total"),
        ("Network Out Total", "Total"),
    ],
    # VM Scale Sets
    "microsoft.compute/virtualmachinescalesets": [
        ("Percentage CPU", "Average"),
        ("Network In Total", "Total"),
        ("Network Out Total", "Total"),
    ],
    # Managed Disks
    "microsoft.compute/disks": [
        ("Composite Disk Read Operations/sec", "Average"),
        ("Composite Disk Write Operations/sec", "Average"),
    ],
    # Azure SQL Database
    "microsoft.sql/servers/databases": [
        ("cpu_percent", "Average"),
        ("connection_successful", "Total"),
        ("storage_percent", "Average"),
    ],
    # Azure SQL Managed Instance
    "microsoft.sql/managedinstances": [
        ("avg_cpu_percent", "Average"),
        ("storage_space_used_mb", "Average"),
    ],
    # App Service Plans
    "microsoft.web/serverfarms": [
        ("CpuPercentage", "Average"),
        ("MemoryPercentage", "Average"),
        ("HttpQueueLength", "Average"),
    ],
    # App Services / Function Apps
    "microsoft.web/sites": [
        ("CpuTime", "Total"),
        ("Requests", "Total"),
        ("BytesReceived", "Total"),
    ],
    # AKS Clusters
    "microsoft.containerservice/managedclusters": [
        ("node_cpu_usage_percentage", "Average"),
        ("node_memory_rss_percentage", "Average"),
        ("kube_node_status_allocatable_cpu_cores", "Average"),
    ],
    # Container Instances
    "microsoft.containerinstance/containergroups": [
        ("CpuUsage", "Average"),
        ("MemoryUsage", "Average"),
        ("NetworkBytesReceivedPerSecond", "Average"),
    ],
    # Azure Cache for Redis
    "microsoft.cache/redis": [
        ("connectedclients", "Average"),
        ("cachehits", "Total"),
        ("cachemisses", "Total"),
    ],
    # Cosmos DB
    "microsoft.documentdb/databaseaccounts": [
        ("TotalRequests", "Total"),
        ("NormalizedRUConsumption", "Average"),
        ("ServerSideLatency", "Average"),
    ],
    # Storage Accounts
    "microsoft.storage/storageaccounts": [
        ("Transactions", "Total"),
        ("Ingress", "Total"),
        ("Egress", "Total"),
    ],
    # Azure Kubernetes Service Node Pools
    "microsoft.containerservice/managedclusters/agentpools": [
        ("node_cpu_usage_percentage", "Average"),
        ("node_memory_rss_percentage", "Average"),
    ],
    # Event Hubs
    "microsoft.eventhub/namespaces": [
        ("IncomingMessages", "Total"),
        ("OutgoingMessages", "Total"),
        ("ActiveConnections", "Average"),
    ],
    # Service Bus
    "microsoft.servicebus/namespaces": [
        ("IncomingMessages", "Total"),
        ("OutgoingMessages", "Total"),
        ("ActiveConnections", "Average"),
    ],
    # Azure Functions (same as web/sites but grouped for clarity)
    "microsoft.web/sites/functions": [
        ("FunctionExecutionCount", "Total"),
        ("FunctionExecutionUnits", "Total"),
    ],
    # API Management
    "microsoft.apimanagement/service": [
        ("TotalRequests", "Total"),
        ("SuccessfulRequests", "Total"),
        ("Capacity", "Average"),
    ],
    # Application Gateway
    "microsoft.network/applicationgateways": [
        ("TotalRequests", "Total"),
        ("CurrentConnections", "Average"),
        ("Throughput", "Average"),
    ],
    # Load Balancers
    "microsoft.network/loadbalancers": [
        ("PacketCount", "Total"),
        ("ByteCount", "Total"),
        ("AllocatedSnatPorts", "Average"),
    ],
    # Azure Databricks
    "microsoft.databricks/workspaces": [
        ("autoOptimizeClusterUtilization", "Average"),
        ("numActiveClusters", "Average"),
    ],
    # HDInsight
    "microsoft.hdinsight/clusters": [
        ("GatewayRequests", "Total"),
        ("CategorizedGatewayRequests", "Total"),
    ],
    # Logic Apps
    "microsoft.logic/workflows": [
        ("RunsStarted", "Total"),
        ("RunsCompleted", "Total"),
        ("RunsFailed", "Total"),
    ],
    # Cognitive Services / OpenAI
    "microsoft.cognitiveservices/accounts": [
        ("TotalCalls", "Total"),
        ("TotalErrors", "Total"),
        ("Latency", "Average"),
    ],
    # Azure Search
    "microsoft.search/searchservices": [
        ("SearchQueriesPerSecond", "Average"),
        ("ThrottledSearchQueriesPercentage", "Average"),
    ],
    # Azure Stream Analytics
    "microsoft.streamanalytics/streamingjobs": [
        ("InputEvents", "Total"),
        ("OutputEvents", "Total"),
        ("ResourceUtilization", "Average"),
    ],
    # Azure Data Factory
    "microsoft.datafactory/factories": [
        ("PipelineRunsStarted", "Total"),
        ("ActivityRunsStarted", "Total"),
        ("TriggerRunsStarted", "Total"),
    ],
}

_AGGREGATION_MAP = {
    "Average": MetricAggregationType.AVERAGE,
    "Total": MetricAggregationType.TOTAL,
    "Minimum": MetricAggregationType.MINIMUM,
    "Maximum": MetricAggregationType.MAXIMUM,
}

_FALLBACK_METRIC_LIMIT = 5


def get_metrics(
    resource_id: str,
    resource_type: str,
    days: int = 90,
    credential: Any = None,
) -> MetricSummary:
    """
    Fetch Azure Monitor metrics for a resource.
    Falls back to querying available metric definitions for unknown resource types.
    """
    metric_defs = _METRICS.get(resource_type.lower())
    if not metric_defs:
        metric_defs = _discover_metrics(resource_id, resource_type, credential)
    if not metric_defs:
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={},
            has_data=False,
        )

    cred = credential or DefaultAzureCredential()
    client = MetricsQueryClient(cred)

    end_time = datetime.now(tz=timezone.utc)
    start_time = end_time - timedelta(days=days)
    granularity = timedelta(days=1)

    metric_names = [name for name, _ in metric_defs]

    try:
        response = client.query_resource(
            resource_uri=resource_id,
            metric_names=metric_names,
            timespan=(start_time, end_time),
            granularity=granularity,
        )
    except HttpResponseError as exc:
        logger.warning(
            "azure_monitor_query_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={},
            has_data=False,
        )

    return _parse_response(response, metric_defs, resource_id, resource_type, days)


def _parse_response(
    response: Any,
    metric_defs: list[tuple[str, str]],
    resource_id: str,
    resource_type: str,
    days: int,
) -> MetricSummary:
    metrics: dict[str, Any] = {}
    has_data = False

    agg_map = {name: agg for name, agg in metric_defs}

    for metric in response.metrics:
        name: str = metric.name
        agg_type: str = agg_map.get(name, "Average")
        values: list[float] = []

        for ts in metric.timeseries:
            for data_point in ts.data:
                val = data_point.total if agg_type == "Total" else data_point.average
                if val is not None:
                    values.append(val)

        if not values:
            metrics[name] = None
            continue

        has_data = True
        metrics[name] = round(
            sum(values) if agg_type == "Total" else sum(values) / len(values), 4
        )

    return MetricSummary(
        resource_id=resource_id,
        resource_type=resource_type,
        period_days=days,
        metrics=metrics,
        has_data=has_data,
    )


def _discover_metrics(
    resource_id: str,
    resource_type: str,
    credential: Any = None,
) -> list[tuple[str, str]]:
    """Auto-discover available metrics for unknown Azure resource types."""
    from azure.monitor.query import MetricsQueryClient

    cred = credential or DefaultAzureCredential()
    client = MetricsQueryClient(cred)
    discovered: list[tuple[str, str]] = []

    try:
        definitions = client.list_metric_definitions(resource_uri=resource_id)
        for defn in definitions:
            metric_name: str = defn.name or ""
            # Pick aggregation based on metric name heuristics
            agg = (
                "Total"
                if any(
                    kw in metric_name.lower()
                    for kw in ("count", "bytes", "requests", "transactions", "total")
                )
                else "Average"
            )
            discovered.append((metric_name, agg))
            if len(discovered) >= _FALLBACK_METRIC_LIMIT:
                break
    except HttpResponseError as exc:
        logger.warning(
            "azure_monitor_list_metrics_failed",
            extra={"resource_id": resource_id, "error": str(exc)},
        )

    return discovered
