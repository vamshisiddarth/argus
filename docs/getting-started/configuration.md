# Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` for local dev.
In Lambda / Cloud Run / Azure Function, set these as environment variables in the deployment.

## AI Provider

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AI_PROVIDER` | No | `bedrock` (Lambda) / `anthropic` (CLI) | `anthropic` \| `bedrock` \| `vertexai` \| `azure_openai` |
| `AI_MODEL` | No | _(per-provider default)_ | Override model for any provider |
| `AI_TEMPERATURE` | No | `0.0` | Model temperature (0.0–1.0) |
| `ANTHROPIC_API_KEY` | When `AI_PROVIDER=anthropic` | — | Anthropic direct API key |
| `BEDROCK_MODEL_ID` | No | `anthropic.claude-sonnet-4-6` | Bedrock model ID |
| `BEDROCK_REGION` | No | `us-east-1` | Region where Bedrock is enabled |
| `VERTEXAI_PROJECT` | When `AI_PROVIDER=vertexai` | — | GCP project for Vertex AI |
| `VERTEXAI_LOCATION` | No | `us-central1` | Vertex AI region |
| `VERTEXAI_MODEL` | No | `google/gemini-1.5-pro-002` | Vertex AI model name |
| `AZURE_OPENAI_ENDPOINT` | When `AI_PROVIDER=azure_openai` | — | e.g. `https://my-resource.openai.azure.com/` |
| `AZURE_OPENAI_DEPLOYMENT` | No | `gpt-4o` | Azure OpenAI deployment name |
| `AZURE_OPENAI_API_KEY` | No | — | Only for local dev without `az login` |

## AWS

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PRIMARY_REGION` | No | `us-east-1` | Region for boto3 session and Bedrock calls |
| `RESOURCE_EXPLORER_REGION` | No | `us-east-1` | Region where your aggregator index lives |
| `IGNORE_REGIONS` | No | _(empty)_ | Comma-separated regions to skip |
| `AWS_PROFILE` | No | _(default profile)_ | Named AWS profile to use |
| `ACCOUNTS_MODE` | No | `single` | `single` \| `multi` |
| `ACCOUNTS_CONFIG` | When `ACCOUNTS_MODE=multi` | — | JSON array of account objects (see below) |

### Multi-account config

You can pass accounts as a JSON env var or via a YAML file:

=== "Environment variable"

    ```ini
    ACCOUNTS_MODE=multi
    ACCOUNTS_CONFIG=[{"id":"111122223333","name":"dev","role_arn":"arn:aws:iam::111122223333:role/ArgusSpokeRole"},{"id":"444455556666","name":"prod","role_arn":"arn:aws:iam::444455556666:role/ArgusSpokeRole"}]
    ```

=== "accounts.yaml (CLI only)"

    ```yaml title="accounts.yaml"
    mode: multi

    accounts:
      - id: "111122223333"
        name: dev
        role_arn: arn:aws:iam::111122223333:role/ArgusSpokeRole
      - id: "444455556666"
        name: prod
        role_arn: arn:aws:iam::444455556666:role/ArgusSpokeRole
    ```

    ```bash
    argus scan --cloud aws --accounts accounts.yaml
    ```

## GCP

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GCP_PROJECT_ID` | Yes (GCP) | — | GCP project to scan |
| `BILLING_BQ_TABLE` | No | — | BigQuery billing export table for cost data |

!!! tip "BigQuery billing export"
    Without `BILLING_BQ_TABLE`, cost fields will show `$0.00`.
    Set it up at: **Billing → Billing export → BigQuery export**

    Format: `project.dataset.gcp_billing_export_v1_XXXXXX`

## Azure

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_SUBSCRIPTION_IDS` | Yes (Azure) | — | Comma-separated subscription IDs |
| `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | No | — | Workspace ID for Activity Log KQL queries |

## Report delivery

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SLACK_WEBHOOK_URL` | No | — | Slack incoming webhook URL |
| `TEAMS_WEBHOOK_URL` | No | — | Microsoft Teams incoming webhook URL |
| `WEBHOOK_URL` | No | — | Generic webhook — receives full JSON report as POST |
| `REPORT_FORMAT` | No | `json,html` | Export formats: `json`, `html`, `pdf`, `pptx` |
| `DRY_RUN` | No | `false` | `true` = log payload to stdout, skip notifications |
| `REPORT_URL_EXPIRY` | No | `604800` | Pre-signed / SAS URL expiry in seconds (default: 7 days) |
| `ADAPTER_CONCURRENCY` | No | `10` | Max parallel metric/activity fetch threads |

At least one notification channel (`SLACK_WEBHOOK_URL`, `TEAMS_WEBHOOK_URL`, or `WEBHOOK_URL`) is required unless `DRY_RUN=true`.

### HTML report storage (optional)

When a report bucket is configured, Argus uploads a self-contained HTML report after each scan and includes a **Full report** button in the Slack digest. Without a bucket, the Slack digest is still sent — it just won't have the button.

| Cloud | Variable | Description |
|-------|----------|-------------|
| AWS | `REPORT_S3_BUCKET` | S3 bucket name. The Lambda execution role needs `s3:PutObject` and `s3:GetObject` on this bucket. |
| GCP | `REPORT_GCS_BUCKET` | GCS bucket name. The Cloud Run service account needs `storage.objectCreator` and `storage.objectViewer`. |
| Azure | `REPORT_STORAGE_ACCOUNT` | Storage account name. The managed identity needs `Storage Blob Data Contributor` on the container. Set `REPORT_STORAGE_CONTAINER` to override the default container name (`argus-reports`). |

The HTML file is self-contained (no external CDN), works offline, and includes a filterable/sortable findings table with expandable AI reasoning rows.

## Scan tuning

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MAX_RESOURCES_PER_SCAN` | No | `200` | Resources passed to the AI after cost-sorting. Raise for large accounts (increases token cost). |
| `METRICS_LOOKBACK_DAYS` | No | `90` | CloudWatch / Cloud Monitoring / Monitor lookback window. Set to `14` for faster local dev. |
| `MAX_AGENT_ITERATIONS` | No | `50` | ReAct loop iteration cap. Increase only if the agent consistently hits the limit on very large accounts. |
| `LLM_BUDGET_USD` | No | `2.00` | Hard spend cap per scan in USD. Set to `0` to disable. |
| `ADAPTER_CONCURRENCY` | No | `10` | Max parallel threads for metric and activity fetches. |

## Logging

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_LEVEL` | No | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

!!! tip "Complete reference"
    See [Environment Variables](../reference/env-vars.md) for the full list including secret manager integration, report storage, and scan tuning details.
