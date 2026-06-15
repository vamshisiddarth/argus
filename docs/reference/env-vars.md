# Environment Variables

Complete reference for all Argus environment variables.

## :material-robot-outline: AI Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `bedrock` (Lambda) · `anthropic` (CLI) | `anthropic` \| `bedrock` \| `vertexai` \| `azure_openai` |
| `ANTHROPIC_API_KEY` | — | Required when `AI_PROVIDER=anthropic` |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-6` | Bedrock model ID |
| `BEDROCK_REGION` | `us-east-1` | Region where Bedrock is enabled |
| `VERTEXAI_PROJECT` | — | Required when `AI_PROVIDER=vertexai` |
| `VERTEXAI_LOCATION` | `us-central1` | Vertex AI region |
| `VERTEXAI_MODEL` | `gemini-1.5-pro-002` | Vertex AI model name |
| `AZURE_OPENAI_ENDPOINT` | — | Required when `AI_PROVIDER=azure_openai` |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4o` | Azure OpenAI deployment name |
| `AZURE_OPENAI_API_VERSION` | `2024-10-21` | Azure OpenAI API version |
| `AZURE_OPENAI_API_KEY` | — | Local dev only — use managed identity in production |

## :material-aws: AWS

| Variable | Default | Description |
|----------|---------|-------------|
| `PRIMARY_REGION` | `us-east-1` | Region for the boto3 session and Bedrock calls |
| `RESOURCE_EXPLORER_REGION` | `us-east-1` | Region where your aggregator index lives |
| `IGNORE_REGIONS` | _(empty)_ | Comma-separated regions to skip (e.g. `ap-east-1,me-south-1`) |
| `AWS_PROFILE` | _(default)_ | Named AWS credentials profile |
| `ACCOUNTS_MODE` | `single` | `single` \| `multi` |
| `ACCOUNTS_CONFIG` | — | JSON array of accounts when `ACCOUNTS_MODE=multi` |

## :material-google-cloud: GCP

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | — | Required for GCP scans |
| `BILLING_BQ_TABLE` | — | BigQuery billing export table for cost data |

## :material-microsoft-azure: Azure

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_SUBSCRIPTION_IDS` | — | Required for Azure scans — comma-separated subscription IDs |
| `AZURE_LOG_ANALYTICS_WORKSPACE_ID` | — | Enables KQL-based Activity Log queries |

## :material-send-outline: Report delivery

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_WEBHOOK_URL` | — | Slack incoming webhook URL |
| `REPORT_S3_BUCKET` | _(empty)_ | S3 bucket for full JSON report (optional) |
| `DRY_RUN` | `false` | `true` = log Slack payload to stdout, skip posting |

## :material-text-box-search-outline: Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

## :material-tune: Scan tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_RESOURCES_PER_SCAN` | `200` | Maximum resources handed to the AI after Phase 0 cost-sorting. Raise for very large accounts (increases AI token cost proportionally). |
| `METRICS_LOOKBACK_DAYS` | `90` | CloudWatch / Cloud Monitoring / Azure Monitor lookback window. 90 days covers quarterly usage patterns and aligns with the CloudTrail lookback. Set to `14` for faster local dev runs — **not recommended in production** as short windows produce false-positive idle findings. |
