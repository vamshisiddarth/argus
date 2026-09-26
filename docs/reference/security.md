# Security Model

Argus is designed to be safe to deploy in production environments. This page documents the security boundaries and data handling.

## Read-only access

Argus uses **read-only IAM roles** on every cloud. It cannot modify, delete, or create any resources in your account. The specific permissions are documented on the [IAM Permissions](iam-permissions.md) page.

| Cloud | Auth method | Scope |
|-------|-------------|-------|
| AWS | IAM execution role (Lambda) or assumed role (multi-account) | Read-only: Resource Explorer, CloudWatch, Cost Explorer, CloudTrail, Describe APIs (plus `s3:PutObject` on its own report bucket) |
| GCP | Service account with viewer roles | Read-only: Asset Inventory, Monitoring, Logging, BigQuery |
| Azure | System-assigned managed identity | Read-only: Resource Graph, Monitor, Cost Management, Activity Log |

## Data collected

During a scan, Argus reads:

- **Resource metadata** — IDs, types, regions, tags, creation dates
- **Usage metrics** — CPU, network, disk I/O, connections (aggregated, not per-request)
- **Cost data** — estimated monthly cost per resource in USD
- **Activity timestamps** — when each resource was last accessed or modified

Argus does **not** read:

- File contents, database records, or application data
- Network traffic or request logs
- Secrets, keys, or credentials stored in your resources
- PII or customer data

## Data flow

```
Cloud APIs → Argus agent (in-memory) ⇄ AI provider → Report
                                                        ↓
                                              Storage (S3/GCS/Blob) + local copy
                                                        ↓
                                     Jira tickets (only if REMEDIATION_ENABLED=true)
                                                        ↓
                                        Slack / Teams / webhook digest
```

1. Resource data is fetched from cloud APIs and held in memory during the scan
2. A compact resource list (IDs, names, types, regions, costs) is sent to the AI provider, which then
   requests metrics and last-activity data for the candidates it chooses to investigate. This is a
   multi-turn conversation (up to `MAX_AGENT_ITERATIONS` calls), plus one call for the executive summary
3. The AI returns findings with waste reasons and recommendations
4. A JSON + HTML report is saved to `LOCAL_REPORT_DIR` and, if configured, to cloud storage
5. If `REMEDIATION_ENABLED=true` and policies match, Jira tickets are created with the finding details
6. A compact digest is posted with a link to the full report
7. In-memory data is discarded when the process exits

## Data retention

| Location | Retention | Encryption |
|----------|-----------|------------|
| Cloud storage (S3/GCS/Blob) | 90 days on S3 (lifecycle rule in the SAM templates); no lifecycle rule is set on GCS or Blob by default — add one if you need it | Encrypted at rest (cloud-native SSE) |
| Local report copies (`LOCAL_REPORT_DIR`) | Until deleted; ephemeral on Lambda / Cloud Run / Functions | Filesystem |
| Jira tickets and `audit.jsonl` (remediation) | Controlled by your Jira instance / until deleted | Jira's encryption / filesystem |
| Pre-signed/SAS URLs | 7 days (configurable via `REPORT_URL_EXPIRY`) | HTTPS in transit |
| Slack messages | Controlled by your Slack workspace retention policy | Slack's encryption |
| Lambda/Cloud Run/Function memory | Ephemeral — discarded after each invocation | N/A |

## AI provider data handling

The AI calls send compact resource data (IDs, names, types, regions, tags, metrics, costs, last-activity timestamps) — not raw cloud API responses. No credentials, secrets, or application data are included.

| Provider | Data path | Retention |
|----------|-----------|-----------|
| AWS Bedrock | Stays in your AWS account. Model invocation logs are off by default. | No training on your data ([AWS policy](https://aws.amazon.com/bedrock/faqs/)) |
| Anthropic API | Sent to Anthropic's API endpoint. | Not used for training. See [Anthropic's privacy policy](https://www.anthropic.com/privacy) |
| Vertex AI / Azure OpenAI | Stays in your cloud account | Governed by your cloud provider agreement |

## Credential handling

- **No hardcoded credentials** — all auth is via environment variables or cloud-native IAM roles
- **Multi-account STS sessions** — temporary credentials, 1-hour expiry, never stored to disk
- **Webhook URLs** — marked `NoEcho` (AWS) / `@secure()` (Azure) in deploy templates
- **API keys** — stored in environment variables, never logged

## Network access

Argus makes outbound HTTPS calls to:

1. Your cloud provider's APIs (same account/project/subscription)
2. The configured AI provider endpoint
3. The notification endpoints you configure (Slack / Teams / generic webhook)
4. Cloud storage for report upload
5. Your Jira instance (only when remediation creates tickets)

No inbound network access is required. The Lambda/Cloud Run/Function does not expose any HTTP endpoints.
