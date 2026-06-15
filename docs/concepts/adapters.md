# Cloud Adapters

Every cloud adapter implements the same four-method contract defined in `adapters/base.py`.
The agent loop never calls cloud SDKs directly — it only calls these methods.

## The contract

```python
class CloudAdapter(ABC):

    def list_resources(
        self,
        ignore_regions: list[str] | None = None,
    ) -> list[Resource]:
        """Return every billable resource, excluding ignored regions."""

    def get_metrics(
        self,
        resource_id: str,
        resource_type: str,
        days: int = 14,
    ) -> MetricSummary:
        """Return usage metrics for the past N days."""

    def get_cost(
        self,
        resource_ids: list[str],
        days: int = 30,
    ) -> dict[str, float]:
        """Return USD cost per resource. Always called with all IDs at once."""

    def get_last_activity(
        self,
        resource_id: str,
        resource_type: str,
    ) -> datetime | None:
        """Return the last meaningful activity timestamp, or None."""
```

## AWS adapter

| Method | AWS service | Notes |
|--------|-------------|-------|
| `list_resources` | Resource Explorer v2 | Aggregator index, paginated, filters non-billable types |
| `get_metrics` | CloudWatch GetMetricData | 43 resource types + dynamic `ListMetrics` fallback |
| `get_cost` | Cost Explorer `GetCostAndUsageWithResources` | Single batched call; requires resource-level data enabled |
| `get_last_activity` | CloudTrail `LookupEvents` | 90-day lookback; filters read-only events |

## GCP adapter

| Method | GCP service | Notes |
|--------|-------------|-------|
| `list_resources` | Cloud Asset Inventory | 22 billable asset types; normalizes zones → regions |
| `get_metrics` | Cloud Monitoring | 15 resource types + dynamic `ListMetricDescriptors` fallback |
| `get_cost` | BigQuery billing export | Parameterized query; falls back to zeros if not configured |
| `get_last_activity` | Cloud Audit Logs | Filters by resource name and service; 90-day lookback |

## Azure adapter

| Method | Azure service | Notes |
|--------|-------------|-------|
| `list_resources` | Resource Graph (KQL) | Cross-subscription, paginated, excludes non-billable types |
| `get_metrics` | Azure Monitor `MetricsQueryClient` | 25 resource types + `list_metric_definitions` fallback |
| `get_cost` | Cost Management `QueryDefinition` | Batched by 50 resource IDs per subscription |
| `get_last_activity` | Log Analytics KQL → Activity Log REST fallback | Filters out read-only operations |

## Resource and MetricSummary types

```python
@dataclass
class Resource:
    resource_id: str        # ARN / full resource path / Azure resource ID
    resource_type: str      # e.g. "AWS::EC2::Instance"
    cloud: str              # "aws" | "gcp" | "azure"
    region: str
    name: str | None        # from Name tag or display name
    tags: dict[str, str]    # all tags

@dataclass
class MetricSummary:
    has_data: bool                   # False if no CloudWatch/Monitoring data exists
    metrics: dict[str, float]        # metric_name → 90-day average value
```

## Non-billable resource filter (AWS)

`list_resources` filters out types that never appear on an AWS bill before returning results:

- All `AWS::IAM::*` (roles, policies, users, groups)
- EC2 primitives: subnets, route tables, network ACLs, DHCP options, internet gateways
- CloudFormation stacks and stacksets
- SSM parameters, documents, patch baselines
- Config rules, Lambda event source mappings, SNS subscriptions, CloudWatch alarms
- And more — see `adapters/aws/resource_explorer.py`

This cuts 60–70% of the resource list before the AI sees it.
