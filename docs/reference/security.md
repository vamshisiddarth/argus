# Security Model

Argus is designed to be safe to deploy in production environments. This page documents the security boundaries and data handling.

## Read-only access

Argus uses **read-only IAM roles** on every cloud. It cannot modify, delete, or create any resources in your account. The specific permissions are documented on the [IAM Permissions](iam-permissions.md) page.

| Cloud | Auth method | Scope |
|-------|-------------|-------|
| AWS | IAM execution role (Lambda) or assumed role (multi-account) | Read-only: Resource Explorer, CloudWatch, Cost Explorer, CloudTrail, Describe APIs |
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
Cloud APIs → Argus agent (in-memory) → AI provider → Report
                                                        ↓
                                              Storage (S3/GCS/Blob)
                                                        ↓
                                                  Slack digest
```

1. Resource data is fetched from cloud APIs and held in memory during the scan
2. A compressed summary is sent to the AI provider for analysis (one batched call)
3. The AI returns findings with waste reasons and recommendations
4. A JSON + HTML report is saved to cloud storage (if configured)
5. A compact Slack digest is posted with a link to the full report
6. All in-memory data is discarded when the function exits

## Data retention

| Location | Retention | Encryption |
|----------|-----------|------------|
| Cloud storage (S3/GCS/Blob) | 90 days (lifecycle rule on S3; configurable on GCS/Blob) | Encrypted at rest (cloud-native SSE) |
| Pre-signed/SAS URLs | 7 days (configurable via `REPORT_URL_EXPIRY`) | HTTPS in transit |
| Slack messages | Controlled by your Slack workspace retention policy | Slack's encryption |
| Lambda/Cloud Run/Function memory | Ephemeral — discarded after each invocation | N/A |

## AI provider data handling

The AI call sends a compressed resource summary (IDs, metrics, costs) — not raw cloud API responses. No credentials, secrets, or application data are included.

| Provider | Data path | Retention |
|----------|-----------|-----------|
| AWS Bedrock | Stays in your AWS account. Model invocation logs are off by default. | No training on your data ([AWS policy](https://aws.amazon.com/bedrock/faqs/)) |
| Anthropic API | Sent to Anthropic's API endpoint. | Not used for training. See [Anthropic's privacy policy](https://www.anthropic.com/privacy) |
| Vertex AI / Azure OpenAI | Phase 8 — same principle: stays in your cloud account | Governed by your cloud provider agreement |

## Credential handling

- **No hardcoded credentials** — all auth is via environment variables or cloud-native IAM roles
- **Multi-account STS sessions** — temporary credentials, 1-hour expiry, never stored to disk
- **Webhook URLs** — marked `NoEcho` (AWS) / `@secure()` (Azure) in deploy templates
- **API keys** — stored in environment variables, never logged

## Network access

Argus makes outbound HTTPS calls to:

1. Your cloud provider's APIs (same account/project/subscription)
2. The configured AI provider endpoint
3. Slack's incoming webhook endpoint
4. Cloud storage for report upload

No inbound network access is required. The Lambda/Cloud Run/Function does not expose any HTTP endpoints.
