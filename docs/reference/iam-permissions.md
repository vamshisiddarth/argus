# IAM Permissions

Argus requires **read-only** permissions. No write permissions are ever requested.

## AWS

### Lambda execution role (single account)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "resource-explorer-2:Search",
        "resource-explorer-2:GetView",
        "cloudwatch:GetMetricData",
        "ce:GetCostAndUsage",
        "ce:GetCostAndUsageWithResources",
        "cloudtrail:LookupEvents",
        "ec2:DescribeInstances",
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "elasticache:DescribeCacheClusters",
        "elasticache:DescribeReplicationGroups",
        "redshift:DescribeClusters",
        "es:DescribeDomain",
        "lambda:GetFunctionConfiguration",
        "dms:DescribeReplicationInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
    }
  ]
}
```

!!! info "Why the describe permissions?"
    Argus uses these read-only `Describe*` calls to fetch the **current instance size**
    (e.g. `db.r5.4xlarge`, `cache.r6g.xlarge`) during metric collection. Without this, the
    AI can only say "consider downsizing." With it, the AI says
    *"RIGHT-SIZE: db.r5.4xlarge → db.r5.2xlarge, saving ~$280/month."*
    All calls are read-only and never modify any resource.

### Additional permissions (optional)

| Permission | Required when |
|------------|--------------|
| `sts:AssumeRole` | `ACCOUNTS_MODE=multi` |
| `s3:PutObject` | `REPORT_S3_BUCKET` is set |

### Spoke role (multi-account)

Each target account needs a role with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "resource-explorer-2:Search",
        "cloudwatch:GetMetricData",
        "ce:GetCostAndUsage",
        "cloudtrail:LookupEvents",
        "ec2:DescribeInstances",
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "elasticache:DescribeCacheClusters",
        "elasticache:DescribeReplicationGroups",
        "redshift:DescribeClusters",
        "es:DescribeDomain",
        "lambda:GetFunctionConfiguration",
        "dms:DescribeReplicationInstances"
      ],
      "Resource": "*"
    }
  ]
}
```

Trust policy — allows the hub Lambda role to assume it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<HUB_ACCOUNT_ID>:role/ArgusLambdaRole"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

!!! warning "Cost Explorer requires activation"
    `ce:GetCostAndUsageWithResources` requires:

    1. Cost Explorer activated for your account
    2. Resource-level data enabled: **Cost Management → Preferences → Resource-level data**

    If not set up, Argus logs a warning and continues with `$0.00` cost values.

## GCP

The Cloud Run service account (`argus-sa@<project>.iam.gserviceaccount.com`) needs:

| Role | Purpose |
|------|---------|
| `roles/cloudasset.viewer` | List all resources via Asset Inventory |
| `roles/monitoring.viewer` | Read Cloud Monitoring metrics |
| `roles/logging.viewer` | Read Cloud Audit Logs |
| `roles/bigquery.dataViewer` | Query BigQuery billing export |
| `roles/bigquery.jobUser` | Run BigQuery jobs |
| `roles/aiplatform.user` | Call Vertex AI Gemini |

## Azure

The Function App managed identity needs:

| Role | Scope | Purpose |
|------|-------|---------|
| `Reader` | Each subscription | List resources, read metadata |
| `Monitoring Reader` | Resource group | Read Azure Monitor metrics |
| `Cost Management Reader` | Each subscription | Read cost data |

!!! tip "Granting subscription-level Reader"
    The Bicep template grants roles at the resource group level.
    For full subscription coverage, also run:

    ```bash
    az role assignment create \
      --assignee <principalId> \
      --role "Reader" \
      --scope /subscriptions/<subscription-id>
    ```
