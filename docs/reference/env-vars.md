# Environment Variables

Complete reference for all Argus environment variables.

## :material-robot-outline: AI Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `bedrock` (Lambda) · `anthropic` (CLI) | `anthropic` \| `bedrock` \| `vertexai` \| `azure_openai` |
| `AI_MODEL` | _(per-provider default)_ | Override the model for any provider. Takes precedence over provider-specific model vars. |
| `AI_TEMPERATURE` | `0.0` | Model temperature (0.0 = deterministic, 1.0 = creative). Applies to all providers. |
| `ANTHROPIC_API_KEY` | — | Required when `AI_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Model name when using Anthropic API directly |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-6` | Bedrock model ID |
| `BEDROCK_REGION` | `us-east-1` | Region where Bedrock is enabled |
| `BEDROCK_MAX_TOKENS` | `2048` | Maximum tokens in Bedrock response |
| `BEDROCK_TEMPERATURE` | `0.3` | Bedrock model temperature |
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
| `TEAMS_WEBHOOK_URL` | — | Microsoft Teams incoming webhook URL |
| `WEBHOOK_URL` | — | Generic webhook URL — receives the full JSON report as a POST body |
| `REPORT_FORMAT` | `json,html` | Comma-separated export formats: `json`, `html`, `pdf`, `pptx`. PDF requires `weasyprint`; PPTX requires `python-pptx` (`pip install argus-cloud-optimizer[export]`). |
| `DRY_RUN` | `false` | `true` = log notification payload to stdout, skip posting |
| `REPORT_URL_EXPIRY` | `604800` | Pre-signed / SAS URL expiry in seconds (default: 7 days) |

### AWS report storage

| Variable | Default | Description |
|----------|---------|-------------|
| `REPORT_S3_BUCKET` | _(empty)_ | S3 bucket for full JSON + HTML reports. When set, the Slack digest includes a "Full report" button linking to a 7-day pre-signed URL. |

### GCP report storage

| Variable | Default | Description |
|----------|---------|-------------|
| `REPORT_GCS_BUCKET` | _(empty)_ | GCS bucket for full JSON + HTML reports. When set, the Slack digest includes a "Full report" button linking to a signed URL. |

### Azure report storage

| Variable | Default | Description |
|----------|---------|-------------|
| `REPORT_STORAGE_ACCOUNT` | _(empty)_ | Azure Storage account name for full JSON + HTML reports. When set, the Slack digest includes a "Full report" button linking to a SAS URL. |
| `REPORT_STORAGE_CONTAINER` | `argus-reports` | Blob container name. Created automatically if it doesn't exist. |

## :material-text-box-search-outline: Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |

## :material-tune: Scan tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_RESOURCES_PER_SCAN` | `200` | Maximum resources handed to the AI after Phase 0 cost-sorting. Raise for very large accounts (increases AI token cost proportionally). |
| `METRICS_LOOKBACK_DAYS` | `90` | CloudWatch / Cloud Monitoring / Azure Monitor lookback window. 90 days covers quarterly usage patterns and aligns with the CloudTrail lookback. Set to `14` for faster local dev runs — **not recommended in production** as short windows produce false-positive idle findings. |
| `ADAPTER_CONCURRENCY` | `10` | Maximum parallel threads for metric and activity fetches during a scan. Increase for large accounts with many resources; decrease if you hit API rate limits. |
| `MAX_AGENT_ITERATIONS` | `50` | Maximum ReAct loop iterations before the agent is forced to stop. Increase only if the agent is consistently hitting the limit on very large accounts. |
| `LLM_BUDGET_USD` | `2.00` | Hard budget for LLM cost per scan in USD. The scan aborts gracefully if this limit is exceeded and returns partial results. Set to `0` to disable the budget check. |

## :material-key-variant: Secret manager integration

Instead of storing sensitive values directly in environment variables, you can point them to a cloud secret manager. Argus resolves secret references at startup before any other processing.

**Supported variables:** `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`, `TEAMS_WEBHOOK_URL`, `WEBHOOK_URL`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`

| Cloud | Pattern | Example |
|-------|---------|---------|
| AWS Secrets Manager | `arn:aws:secretsmanager:<region>:<account>:secret:<name>` | `ANTHROPIC_API_KEY=arn:aws:secretsmanager:us-east-1:123456789012:secret:argus/api-key` |
| GCP Secret Manager | `gcp-secret://<project>/<secret>[/<version>]` | `SLACK_WEBHOOK_URL=gcp-secret://my-project/slack-webhook` |
| Azure Key Vault | `akv://<vault-name>/<secret-name>` | `ANTHROPIC_API_KEY=akv://my-vault/anthropic-key` |

The required SDK must be installed for the cloud you reference — `boto3` for AWS, `google-cloud-secret-manager` for GCP, `azure-keyvault-secrets` + `azure-identity` for Azure. If the value doesn't match any pattern, it's used as-is (no SDK required).
