# Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` for local dev.
In Lambda / Cloud Run / Azure Function, set these as environment variables in the deployment.

## AI Provider

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AI_PROVIDER` | No | `bedrock` (Lambda) / `anthropic` (CLI) | `anthropic` \| `bedrock` \| `vertexai` \| `azure_openai` |
| `ANTHROPIC_API_KEY` | When `AI_PROVIDER=anthropic` | — | Anthropic direct API key |
| `BEDROCK_MODEL_ID` | No | `anthropic.claude-sonnet-4-6` | Bedrock model ID |
| `BEDROCK_REGION` | No | `us-east-1` | Region where Bedrock is enabled |
| `VERTEXAI_PROJECT` | When `AI_PROVIDER=vertexai` | — | GCP project for Vertex AI |
| `VERTEXAI_LOCATION` | No | `us-central1` | Vertex AI region |
| `VERTEXAI_MODEL` | No | `gemini-1.5-pro-002` | Vertex AI model name |
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
    python main.py --cloud aws --run-now --accounts accounts.yaml
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
| `SLACK_WEBHOOK_URL` | Yes* | — | Slack incoming webhook URL |
| `REPORT_S3_BUCKET` | No | — | S3 bucket to save the full JSON report |
| `DRY_RUN` | No | `false` | `true` = log payload to stdout, skip Slack post |

*Not required when `DRY_RUN=true`

## Logging

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_LEVEL` | No | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
