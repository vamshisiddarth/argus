<p align="center">
  <img src="docs/assets/images/logo-full.svg" alt="Argus" height="72">
</p>

<p align="center"><strong>AI-powered cloud cost optimization agent for AWS, GCP, and Azure.</strong></p>

Argus finds idle and wasted cloud resources — stopped EC2 instances, unattached EBS volumes, orphaned Elastic IPs, underutilized RDS databases — and delivers a prioritized, AI-reasoned report to Slack every week.

[![CI](https://github.com/vamshisiddarth/argus/actions/workflows/ci.yml/badge.svg)](https://github.com/vamshisiddarth/argus/actions/workflows/ci.yml)
[![Publish](https://github.com/vamshisiddarth/argus/actions/workflows/publish.yml/badge.svg)](https://github.com/vamshisiddarth/argus/actions/workflows/publish.yml)
[![PyPI](https://img.shields.io/pypi/v/argus-cloud-optimizer.svg)](https://pypi.org/project/argus-cloud-optimizer/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/argus-cloud-optimizer.svg)](https://pypi.org/project/argus-cloud-optimizer/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-vamshisiddarth.github.io%2Fargus-blue)](https://vamshisiddarth.github.io/argus/)

```text
Argus — AWS Waste Report (2026-06-24)

💸 $1,432.85/month estimated waste
📊 6 idle resources across 1 account

Six resources were identified as idle or over-provisioned. The RDS instance
accounts for 87% of waste and should be right-sized immediately.

─────────────────────────────────────
Top findings
🔴 db-analytics-01  · RDS         · $1,240.00/mo
🔴 cache-prod-001   · ElastiCache  ·   $142.00/mo
🔴 i-0abc123def     · EC2          ·    $28.40/mo
🟡 nat-0def456      · NAT Gateway  ·    $10.80/mo
🟡 vol-orphan       · EBS          ·     $8.00/mo
⚪ +1 more finding in the full report

[ 📄 Full report (HTML) ]  [ vamshisiddarth/argus ]
```

---

## What it does

Every week (or on demand), Argus:

1. **Discovers** every resource in your cloud account using AWS Resource Explorer / GCP Asset Inventory / Azure Resource Graph
2. **Analyzes** each candidate — CloudWatch/Cloud Monitoring/Azure Monitor metrics, Cost Explorer/BigQuery/Cost Management cost data, and CloudTrail/Audit Log/Activity Log last-activity timestamps
3. **Reasons** about idleness using Claude (via AWS Bedrock, Anthropic API, or Vertex AI) — no hardcoded thresholds
4. **Reports** a compact digest (Slack, Microsoft Teams, or generic webhook) with top findings and a link to a full self-contained HTML report

The **Full report** button links to a self-contained HTML file (S3 / GCS / Azure Blob) with a filterable/sortable table and expandable AI reasoning per finding. Works offline, no login required.

> **See realistic examples:** [`sample-report-aws.json`](examples/sample-report-aws.json) · [`sample-report-gcp.json`](examples/sample-report-gcp.json) · [`sample-report-azure.json`](examples/sample-report-azure.json) — 5 findings each with AI-written reasoning, metrics, and cost data.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Loop (ReAct)                   │
│   Think → Call Tool → Observe → Think → Submit          │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
  CloudAdapter               AIProvider
  (AWS / GCP / Azure)        (Bedrock / Anthropic / Vertex)
        │
   ┌────┴──────────────────┐
   │  list_resources       │  Resource Explorer / Asset Inventory / Resource Graph
   │  get_metrics          │  CloudWatch / Cloud Monitoring / Azure Monitor
   │  get_cost             │  Cost Explorer / BigQuery / Cost Management
   │  get_last_activity    │  CloudTrail / Audit Logs / Activity Log
   └───────────────────────┘
```

**Design principle: Same brain. Different hands. Different home.**
- **Brain** = agent loop + AI reasoning (`core/`) — pure Python, zero cloud imports
- **Hands** = cloud adapters (`adapters/`) — swappable per cloud
- **Home** = entrypoints (`entrypoints/`) — Lambda / Cloud Run / Azure Function

---

## Quick start

### Option A — Docker (fastest)

```bash
docker build --build-arg CLOUD=aws -t argus .

docker run --rm \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e DRY_RUN=true \
  -v ~/.aws:/root/.aws:ro \
  argus --cloud aws --run-now --dry-run
```

### Option B — Install from PyPI

**Prerequisites**
- Python 3.11+
- Cloud credentials configured (see below)
- An Anthropic API key **or** cloud-native AI access (Bedrock / Vertex AI / Azure OpenAI)

```bash
pip install argus-cloud-optimizer
argus --version   # argus 0.3.0
argus --help
```

One package — all three clouds included. No extras needed. `--cloud` auto-detects from your environment (GCP_PROJECT_ID / AZURE_SUBSCRIPTION_IDS / AWS credentials), or specify explicitly.

> **Verified 2026-06-21:** `pip install argus-cloud-optimizer && argus --version` works on a clean Python 3.11/3.12/3.13 venv with no project files.

**AWS:**

```bash
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export DRY_RUN=true
argus scan --cloud aws --dry-run
# or just: argus scan  (auto-detects from AWS_PROFILE / AWS_ACCESS_KEY_ID)
```

> Enable [Resource Explorer](https://docs.aws.amazon.com/resource-explorer/latest/userguide/) with an **aggregator index** in `us-east-1` (or set `RESOURCE_EXPLORER_REGION`).

**GCP:**

```bash
export GCP_PROJECT_ID=my-project-123
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export DRY_RUN=true
argus scan --cloud gcp --dry-run
# or just: argus scan  (auto-detects from GCP_PROJECT_ID)
```

> Requires BigQuery billing export enabled for cost data.

**Azure:**

```bash
export AZURE_SUBSCRIPTION_IDS=sub-id-1,sub-id-2
export AI_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export DRY_RUN=true
argus scan --cloud azure --dry-run
# or just: argus scan  (auto-detects from AZURE_SUBSCRIPTION_IDS)
```

### Option C — Clone and develop

```bash
git clone https://github.com/vamshisiddarth/argus.git
cd argus
pip install -e ".[all,dev]"
cp .env.example .env                       # edit with your values
argus --cloud aws --run-now
```

### Interactive Chat Mode

Ask questions about your cloud infrastructure in natural language:

```bash
pip install argus-cloud-optimizer[chat]   # optional: adds rich formatting
argus chat --cloud aws --ai-provider anthropic   # explicit cloud
argus chat                                       # auto-detects cloud
```

```
Argus v0.3.0 — Interactive Cloud Cost Assistant
Cloud: AWS  |  Accounts: prod (123456789012)  |  Budget: $1.00/session
Tip: end a line with \ to continue on the next line.
Type your question, or /help for commands.

argus> What's costing the most and not doing anything?

  → Scanning resources
  → Fetching cost data

Argus: Three idle resources account for $73.30/mo in waste:
  • nat-0abc123 (NAT Gateway, us-east-1) — $32.50/mo — 847 bytes in 90 days, delete it
  • db-prod-replica (RDS, us-west-2) — $28.80/mo — zero connections, read replica with no readers
  • vol-0def456 (EBS, us-east-1) — $12.00/mo — unattached since 2026-03-15

[this turn: 2,847 in / 412 out, $0.0147 | session: 2,847 in / 412 out, $0.0147 / $1.00 budget]

argus> Is the RDS replica definitely safe to delete?

  → Fetching metrics: db-prod-replica
  → Checking last activity: db-prod-replica

Argus: Yes. db-prod-replica is confirmed idle — CPU avg 0.1%, DatabaseConnections avg 0,
last activity 2026-03-21 (93 days ago). The primary db-prod is fully active; this replica
has no readers. Safe to snapshot and delete. Saves $28.80/mo.

[this turn: 1,923 in / 187 out, $0.0089 | session: 4,770 in / 599 out, $0.0236 / $1.00 budget]

argus> What would our total monthly bill look like after cleaning all three up?

Argus: Current waste: $73.30/mo across the three resources. Deleting all three saves
$879.60/year. Your remaining infrastructure cost is unchanged — none of these have
active dependencies based on metrics and activity logs.

[this turn: 1,102 in / 98 out, $0.0047 | session: 5,872 in / 697 out, $0.0283 / $1.00 budget]

argus> /summary
Summarizing conversation...
Done — earlier turns condensed into context.

argus> Remind me which one had the highest monthly cost?

Argus: nat-0abc123 (NAT Gateway, us-east-1) at $32.50/mo — negligible traffic over 90 days.
```

Available REPL commands: `/help`, `/scan`, `/cost`, `/clear`, `/summary`, `/quit`

### CLI Options

```
argus scan [--cloud aws|gcp|azure] [options]    # full batch scan
argus chat [--cloud aws|gcp|azure] [options]    # interactive Q&A
argus --run-now --cloud aws [options]           # backward compat

  --cloud CLOUD              Cloud provider (auto-detected from env vars if omitted)
  -V, --version              Show version and exit
  --dry-run                  Print notification payload instead of posting
  --ignore-regions REGIONS   Comma-separated regions to skip (e.g. ap-east-1,me-south-1)
  --ai-provider PROVIDER     anthropic | bedrock | vertexai | azure_openai (default: anthropic)
  --accounts PATH            Path to accounts.yaml for multi-account/project/subscription mode
  --max-resources N          Maximum resources to analyze per scan (default: 200)
  --lookback-days DAYS       Metrics lookback window in days (default: 90, use 14 for faster local dev)
  --llm-budget USD           Cost budget per scan/session (default: $2.00 scan, $1.00 chat)
```

---

## Deploy to AWS Lambda

Uses [AWS SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) — handles packaging and upload automatically. No S3 bucket needed.

### Single account

```bash
make deploy-aws
# or manually:
cd deploy/aws/single-account
sam build && sam deploy --guided
```

`sam deploy --guided` walks you through parameters (Slack webhook, region, AI provider) and saves them to `samconfig.toml` for future deploys. Subsequent deploys are just `sam deploy`.

The stack creates:
- Lambda function (runs weekly via EventBridge)
- IAM role with least-privilege read-only permissions
- S3 bucket for full JSON report storage (90-day retention)

### Multi-account

**Hub account** (runs Argus):

```bash
make deploy-aws-multi
# or manually:
cd deploy/aws/multi-account/hub
sam build && sam deploy --guided
```

**Each spoke account** (read-only IAM role only — no Lambda):

```bash
aws cloudformation deploy \
  --template-file deploy/aws/multi-account/spoke-role.yaml \
  --stack-name Argus-Spoke \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides HubAccountId=<hub-account-id>
```

The hub stack output includes the `HubRoleArn` — use it as the `HubRoleArn` parameter for spoke deployments.

---

## Deploy to GCP (Cloud Run)

```bash
# Authenticate
gcloud auth application-default login

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Deploy
bash deploy/gcp/deploy.sh
```

Requires: Cloud Run API, Cloud Scheduler API, BigQuery billing export enabled.

---

## Deploy to Azure (Function App)

```bash
# Authenticate
az login

# Deploy
az deployment group create \
  --resource-group Argus-RG \
  --template-file deploy/azure/function-app.bicep \
  --parameters subscriptionIds="sub-id-1,sub-id-2" \
               slackWebhookUrl="https://hooks.slack.com/services/..."
```

---

## AI providers

| Provider | Use case | Setup |
|----------|----------|-------|
| Anthropic API | Local dev, any cloud | Set `ANTHROPIC_API_KEY` |
| AWS Bedrock | AWS production | IAM role — no key needed |
| Vertex AI (Gemini) | GCP production | ADC — no key needed |
| Azure OpenAI (GPT-4o) | Azure production | Managed identity — no key needed |

Set `AI_PROVIDER=anthropic|bedrock|vertexai|azure_openai` in `.env` or the deployment environment. Use `AI_MODEL` to override the model for any provider, and `AI_TEMPERATURE` to control creativity (default: `0.0`).

---

## Multi-account / multi-project setup

Create `accounts.yaml` with the key matching your cloud:

**AWS** (hub/spoke with STS AssumeRole):

```yaml
mode: multi

accounts:
  - id: "111122223333"
    name: dev
    role_arn: arn:aws:iam::111122223333:role/ArgusSpokeRole
  - id: "444455556666"
    name: prod
    role_arn: arn:aws:iam::444455556666:role/ArgusSpokeRole
```

**GCP** (one scan per project, ADC handles auth):

```yaml
mode: multi

projects:
  - id: my-project-dev
    name: dev
  - id: my-project-prod
    name: production
```

Or set `GCP_PROJECT_IDS=my-project-dev,my-project-prod` instead.

**Azure** (cross-subscription via Resource Graph):

```yaml
mode: multi

subscriptions:
  - id: "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
    name: dev
  - id: "11112222-3333-4444-5555-666677778888"
    name: production
```

Or set `AZURE_SUBSCRIPTION_IDS=sub-1,sub-2` instead.

Then run:

```bash
argus scan --cloud aws --accounts accounts.yaml
argus scan --cloud gcp --accounts accounts.yaml
argus scan --cloud azure --accounts accounts.yaml
```

---

## IAM permissions (AWS)

Argus needs **read-only** access. The Lambda execution role requires:

```
resource-explorer-2:Search
resource-explorer-2:GetView
cloudwatch:GetMetricData
ce:GetCostAndUsage
ce:GetCostAndUsageWithResources
cloudtrail:LookupEvents
bedrock:InvokeModel          # only if AI_PROVIDER=bedrock
sts:AssumeRole               # only for multi-account mode
s3:PutObject                 # only if REPORT_S3_BUCKET is set
```

No write permissions are ever requested.

> **Cost Explorer note:** `GetCostAndUsageWithResources` requires resource-level cost allocation
> to be enabled in AWS Cost Management → Preferences → Resource-level data.
> If not enabled, Argus logs a warning and continues — cost fields will show $0.00.

---

## IAM permissions (GCP)

Argus needs **read-only** access. The service account (`argus-sa@PROJECT.iam.gserviceaccount.com`) requires:

```
cloudasset.assets.listAssets        # list all resources (Asset Inventory API)
monitoring.timeSeries.list          # read CPU / memory / request metrics
monitoring.metricDescriptors.list   # discover available metric types
logging.logEntries.list             # read Cloud Audit Logs for last-activity timestamps
bigquery.jobs.create                # only if BILLING_BQ_TABLE is set
bigquery.tables.getData             # only if BILLING_BQ_TABLE is set
aiplatform.endpoints.predict        # only if AI_PROVIDER=vertexai (default)
storage.objects.create              # only if REPORT_GCS_BUCKET is set
storage.objects.get                 # only if REPORT_GCS_BUCKET is set
iam.serviceAccounts.signBlob        # only if REPORT_GCS_BUCKET is set
```

No write permissions are ever requested.

The deploy script binds `roles/cloudasset.viewer`, `roles/monitoring.viewer`, and `roles/logging.viewer` automatically. For a tighter permission surface, create a custom role using only the exact permissions above — see [GCP deployment docs](docs/deployment/gcp.md#iam-permissions) for the one-command setup.

> **BigQuery note:** without `BILLING_BQ_TABLE`, cost fields show `$0.00` — resource
> discovery and idleness detection still work via metrics and audit logs.

---

## IAM permissions (Azure)

Argus needs **read-only** access. The Managed Identity requires:

```
Microsoft.ResourceGraph/resources/action                              # list all resources (Resource Graph KQL)
Microsoft.Insights/metrics/read                                       # read CPU / memory / request metrics
Microsoft.Insights/metricDefinitions/read                             # discover available metric types
Microsoft.Insights/eventtypes/management/values/read                  # Activity Log fallback for last-activity
Microsoft.CostManagement/query/action                                 # run cost queries
Microsoft.CostManagement/*/read                                       # read cost data
Microsoft.OperationalInsights/workspaces/query/read                   # only if logAnalyticsWorkspaceId is set
Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write # only if reportStorageAccount is set
Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read  # only if reportStorageAccount is set
```

No write permissions are ever requested.

The built-in `Reader` + `Cost Management Reader` roles cover all required actions per subscription. For a tighter permission surface, create a custom role using only the exact actions above — see [Azure deployment docs](docs/deployment/azure.md#iam-permissions) for the one-command setup.

> **Cost Management note:** `Reader` covers `*/read` but cost queries use a `query/action`
> verb. `Cost Management Reader` must be added separately — without it, cost fields show `$0.00`.

---

## Limitations & known issues

Before you invest time deploying Argus, know what it **can't** do yet:

| Area | Status | Details |
|------|--------|---------|
| **Resource discovery** | All three strong | AWS covers 43 resource types via Resource Explorer. GCP covers 31 asset types via Asset Inventory. Azure discovers all types via Resource Graph with 40 having curated metric mappings. All three fall back to dynamic metric auto-discovery for unmapped types. AWS has the deepest per-type metric coverage; GCP and Azure are catching up. |
| **Cost accuracy** | Best-effort | AWS Cost Explorer charges $0.01/API call — Argus batches aggressively (max 2 calls/scan). GCP requires BigQuery billing export enabled. Azure cost data depends on subscription-level access. Resource-level cost allocation must be enabled in AWS for per-resource costs; without it, costs show $0.00. |
| **AI non-determinism** | By design | The AI decides what's idle — different runs may produce slightly different findings or reasoning. Set `AI_TEMPERATURE=0.0` (default) for most consistent results. |
| **LLM cost** | Configurable | A full scan of ~200 resources costs ~$0.05–$0.50 in LLM API fees depending on provider. Use `--llm-budget` to set a hard cap (default: $2.00/scan). Large estates (1000+ resources) will hit the budget limit — increase it or use `--max-resources`. |
| **AWS Resource Explorer setup** | Manual step | You must enable Resource Explorer with an **aggregator index** (typically in `us-east-1`). Without this, Argus cannot discover resources. This is a one-time setup but is easy to miss. |
| **Write actions** | None | Argus is read-only. It reports findings but never deletes, stops, or modifies resources. Remediation is manual. |
| **Multi-cloud in one scan** | Not yet | Each `argus` invocation scans one cloud. Use the merge report feature (`core/reports/multi_cloud.py`) to combine results after separate runs. |
| **Notifications** | Slack + Teams + webhook | No email. Slack/Teams delivery requires a webhook URL. |

### Multi-cloud maturity

AWS has the richest experience — it was developed first, has the most resource types with curated metric mappings, and has a mature multi-account hub/spoke deployment model. GCP and Azure are fully functional but the AWS adapter has been battle-tested more extensively. Cost data depth also varies: AWS Cost Explorer with resource-level allocation is the most reliable, GCP requires BigQuery billing export to be configured, and Azure Cost Management depends on subscription-level access. All three clouds have dynamic metric fallback for unmapped resource types, so even uncurated types get some signal.

### Multi-cloud parity

| Capability | AWS | GCP | Azure |
|-----------|-----|-----|-------|
| Resource discovery | 43 types (Resource Explorer) | 31 types (Asset Inventory) | All types (Resource Graph) |
| Metrics | CloudWatch (43 types + fallback) | Cloud Monitoring (31 types + fallback) | Azure Monitor (40 types + fallback) |
| Cost data | Cost Explorer (batched) | BigQuery billing export | Cost Management API |
| Last activity | CloudTrail (90-day lookback) | Cloud Audit Logs | Activity Log / Log Analytics |
| Deployment | Lambda (SAM) | Cloud Run Job | Azure Function (Bicep) |
| Multi-account | Hub/spoke with STS | Multi-project (per-project scan) | Cross-subscription via Resource Graph |
| Secret management | Secrets Manager | Secret Manager | Key Vault |

---

## Running tests

```bash
make test                  # unit tests only (528 tests, no cloud creds needed)
make test-integration      # integration tests (32 tests — adapter contracts, report schema)
make test-all              # everything (560 tests)
```

Tests use `unittest.mock` throughout — no real AWS/GCP/Azure calls are made.

---

## Project structure

```
argus/
├── core/                  # Pure Python — no cloud imports
│   ├── agent/loop.py      # ReAct agent loop
│   ├── agent/prompts.py   # System prompt + tool schemas
│   ├── models/finding.py  # ResourceFinding dataclass
│   └── reports/           # Report generator, multi-cloud merge, export, notifications
├── adapters/
│   ├── base.py            # CloudAdapter abstract class
│   ├── aws/               # AWS adapter (Resource Explorer, CloudWatch, Cost Explorer, CloudTrail)
│   ├── gcp/               # GCP adapter (Asset Inventory, Cloud Monitoring, BigQuery, Audit Logs)
│   └── azure/             # Azure adapter (Resource Graph, Monitor, Cost Management, Activity Log)
├── ai/
│   ├── base.py            # AIProvider abstract class
│   ├── anthropic.py       # Anthropic API (local dev / universal fallback)
│   ├── bedrock.py         # AWS Bedrock (Converse API)
│   ├── vertexai.py        # Vertex AI / Gemini (GCP)
│   └── azure_openai.py    # Azure OpenAI / GPT-4o (Azure)
├── entrypoints/
│   ├── cli.py             # argus --cloud aws --run-now
│   ├── aws_lambda.py      # AWS Lambda handler
│   ├── gcp_cloudrun.py    # GCP Cloud Run Job handler
│   └── azure_function.py  # Azure Function timer trigger
├── deploy/
│   ├── aws/               # CloudFormation templates
│   ├── gcp/               # Cloud Run + Scheduler deploy script
│   └── azure/             # Bicep templates
└── tests/                 # 560 tests, all pass offline
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT
