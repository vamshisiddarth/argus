# IAM Permissions

Argus requires **read-only** permissions. No write permissions are ever requested.

## AWS

The policies below are taken from the CloudFormation templates in `deploy/aws/`. Deploying
the templates creates them for you.

### Lambda execution role (single account)

`deploy/aws/single-account/template.yaml` creates `ArgusLambdaRole-<region>` with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "resource-explorer-2:Search",
        "resource-explorer-2:GetView",
        "resource-explorer-2:ListIndexes",
        "resource-explorer-2:ListSupportedResourceTypes",
        "resource-explorer-2:GetIndex",
        "resource-explorer-2:GetDefaultView",
        "resource-explorer-2:ListViews",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "ce:GetCostAndUsage",
        "ce:GetCostAndUsageWithResources",
        "cloudtrail:LookupEvents",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeAddresses",
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "elasticache:DescribeCacheClusters",
        "elasticache:DescribeReplicationGroups",
        "redshift:DescribeClusters",
        "es:DescribeDomain",
        "lambda:GetFunctionConfiguration",
        "dms:DescribeReplicationInstances",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:<BedrockRegion>::foundation-model/<BedrockModelId>"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::argus-reports-<account>-<region>/*"
    }
  ]
}
```

!!! info "Why the extra Resource Explorer permissions?"
    Before every scan Argus runs a preflight that checks the aggregator index
    (`ListIndexes`, `GetIndex`), the default view and its `tags` property
    (`GetDefaultView`, `GetView`), and that `Search` works. Without them the
    scan stops with exit code 4 and a message naming what is missing. See
    [Troubleshooting](troubleshooting.md#preflight-checks).

### Dedicated read-only scan role

Two ways to give a person or CI job a scan role that is not an administrator:

| Option | Policy | When to use |
|---|---|---|
| Minimal (default) | Only the actions listed above | Least privilege; what Argus actually calls |
| `ReadOnlyAccess` + additions | AWS managed `ReadOnlyAccess` plus the Resource Explorer and Cost Explorer actions | Easier to audit against a standard policy. `ReadOnlyAccess` alone is not enough: it does not include the Resource Explorer actions Argus needs |

[`deploy/aws/read-only-scan-role.yaml`](https://github.com/vamshisiddarth/argus/blob/main/deploy/aws/read-only-scan-role.yaml)
creates either variant (`UseAwsReadOnlyAccess=true|false`). Then scan with a guard
against a wrong profile:

```bash
argus scan --cloud aws --expect-account 123456789012
```

`--expect-account` (or `ARGUS_EXPECT_ACCOUNT`) aborts with exit code 4 before any cloud
or LLM call when the credentials belong to a different account. It applies to
single-account scans.

Do not scan with an administrator role. A copy-paste Terraform role with exactly
the permissions above is in
[`deploy/aws/terraform/read-only-scan-role.tf`](https://github.com/vamshisiddarth/argus/blob/main/deploy/aws/terraform/read-only-scan-role.tf);
the CloudFormation templates in `deploy/aws/` create the same set. Argus prints
the identity it runs as at the start of every scan and warns when the name
looks like `Administrator*` or `*FullAccess`.

!!! info "Why the describe permissions?"
    Argus uses these read-only `Describe*` calls to fetch the **current instance size**
    (e.g. `db.r5.4xlarge`, `cache.r6g.xlarge`) during metric collection. Without this, the
    AI can only say "consider downsizing." With it, the AI says
    *"RIGHT-SIZE: db.r5.4xlarge → db.r5.2xlarge, saving ~$280/month."*
    All calls are read-only and never modify any resource.

`cloudwatch:ListMetrics` powers the dynamic metric discovery used for resource types that
aren't in the registry.

### Hub role (multi-account)

`deploy/aws/multi-account/hub/template.yaml` creates `ArgusHubRole-<region>`. It scans nothing
itself; it only needs `sts:AssumeRole` on the spoke roles, `sts:GetCallerIdentity`,
`bedrock:InvokeModel`, and `s3:PutObject` / `s3:GetObject` on the report bucket.

### Spoke role (multi-account)

`deploy/aws/multi-account/spoke-role.yaml` creates `ArgusSpokeRole` in each target account with
the same read-only scan permissions as the single-account role (without Bedrock, S3, or STS):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "resource-explorer-2:Search",
        "resource-explorer-2:GetView",
        "resource-explorer-2:ListIndexes",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
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
    }
  ]
}
```

Trust policy — allows only the hub role (the `HubRoleArn` output of the hub stack) to assume it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<HUB_ACCOUNT_ID>:role/ArgusHubRole-<region>"
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
| `roles/aiplatform.user` | Call Vertex AI Gemini (only if `AI_PROVIDER=vertexai`) |
| `roles/storage.objectCreator` + `roles/storage.objectViewer` (bucket) | Upload reports (only if `REPORT_GCS_BUCKET` is set) |
| `roles/iam.serviceAccountTokenCreator` (on the SA itself) | Sign the report URL (only if `REPORT_GCS_BUCKET` is set) |

`deploy/gcp/deploy.sh` grants all of these. See [GCP deployment](../deployment/gcp.md#iam-permissions) for details.

## Azure

The Function App managed identity needs:

| Role | Scope | Purpose | Granted by Bicep? |
|------|-------|---------|-------------------|
| `Reader` | Each subscription to scan | Resource Graph, Monitor metrics, Activity Log | No — grant manually |
| `Cost Management Reader` | Each subscription to scan | Read cost data | Resource group only — grant per subscription manually |
| `Monitoring Reader` | Resource group | Read Azure Monitor metrics (also covered by `Reader`) | Yes |
| `Log Analytics Reader` | Log Analytics workspace | Activity Log KQL queries (only if `AZURE_LOG_ANALYTICS_WORKSPACE_ID` is set) | No |
| `Storage Blob Data Contributor` + `Storage Blob Delegator` | Report storage account | Upload reports and sign the SAS link (only if `REPORT_STORAGE_ACCOUNT` is set) | Yes, when `reportStorageAccount` is passed |

!!! tip "Granting subscription-level roles"
    The Bicep template only grants roles at the resource group level.
    For each subscription you want to scan, run:

    ```bash
    for ROLE in "Reader" "Cost Management Reader"; do
      az role assignment create \
        --assignee <principalId> \
        --role "$ROLE" \
        --scope /subscriptions/<subscription-id>
    done
    ```
