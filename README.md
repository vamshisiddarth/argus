<p align="center">
  <img src="docs/assets/images/logo-full.svg" alt="Argus" height="72">
</p>

<p align="center"><strong>AI-powered cloud cost optimization agent for AWS, GCP, and Azure.</strong></p>

Argus finds idle and wasted cloud resources — stopped EC2 instances, unattached EBS volumes, orphaned Elastic IPs, underutilized RDS databases — and delivers a prioritized, AI-reasoned report to Slack every week.

[![CI](https://github.com/vamshisiddarth/argus/actions/workflows/ci.yml/badge.svg)](https://github.com/vamshisiddarth/argus/actions/workflows/ci.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What it does

Every week (or on demand), Argus:

1. **Discovers** every resource in your cloud account using AWS Resource Explorer / GCP Asset Inventory / Azure Resource Graph
2. **Analyzes** each candidate — CloudWatch/Cloud Monitoring/Azure Monitor metrics, Cost Explorer/BigQuery/Cost Management cost data, and CloudTrail/Audit Log/Activity Log last-activity timestamps
3. **Reasons** about idleness using Claude (via AWS Bedrock, Anthropic API, or Vertex AI) — no hardcoded thresholds
4. **Reports** findings to Slack ranked by monthly waste, with plain-English explanations and actionable recommendations

Example Slack output:

```
Argus found $42.65/month in waste across 4 resources

HIGH  i-0abc123def  EC2 t3.large       $28.40/mo  CPU avg 0.0014% over 14 days
HIGH  nat-0def456   NAT Gateway        $10.80/mo  Zero bytes transferred — no traffic
MED   vol-orphan    EBS 100 GiB gp3    $8.00/mo   Unattached, no I/O in 30 days
LOW   eipalloc-xyz  Elastic IP         $3.65/mo   Unassociated since creation
```

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

## Quick start — local AWS scan

### Prerequisites
- Python 3.13+
- AWS credentials configured (`~/.aws/credentials` or environment variables)
- AWS Resource Explorer enabled with an **aggregator index** in `us-east-1`
  (or set `RESOURCE_EXPLORER_REGION` to your aggregator region)
- An Anthropic API key **or** AWS Bedrock access

### 1. Clone and install

```bash
git clone https://github.com/vamshisiddarth/argus.git
cd argus
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` — minimum required:

```ini
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../...
# or set DRY_RUN=true to print the Slack payload instead of posting it
DRY_RUN=true
```

### 3. Run

```bash
python main.py --cloud aws --run-now --dry-run
```

The agent will scan your account and print the Slack payload to stdout. Remove `--dry-run` to post to Slack.

### Options

```
python main.py --cloud aws --run-now [options]

  --dry-run                  Print Slack payload instead of posting
  --ignore-regions REGIONS   Comma-separated regions to skip (e.g. ap-east-1,me-south-1)
  --ai-provider PROVIDER     anthropic | bedrock (default: anthropic)
  --accounts PATH            Path to accounts.yaml for multi-account mode
```

---

## Deploy to AWS Lambda

### Single account — one-click

[![Launch Stack](https://s3.amazonaws.com/cloudformation-examples/cloudformation-launch-stack.png)](https://console.aws.amazon.com/cloudformation/home#/stacks/create/review?templateURL=https://raw.githubusercontent.com/vamshisiddarth/argus/main/deploy/aws/single-account.yaml)

Or deploy manually:

```bash
aws cloudformation deploy \
  --template-file deploy/aws/single-account.yaml \
  --stack-name Argus \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      SlackWebhookUrl=https://hooks.slack.com/services/... \
      PrimaryRegion=us-east-1
```

The template creates:
- Lambda function (runs weekly via EventBridge Scheduler)
- IAM role with least-privilege read-only permissions
- Resource Explorer aggregator index (if not already present)

### Multi-account

Deploy the hub in the account that will run Argus:

```bash
aws cloudformation deploy \
  --template-file deploy/aws/multi-account/hub.yaml \
  --stack-name Argus-Hub \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides SlackWebhookUrl=https://hooks.slack.com/services/...
```

Then deploy the spoke role in each target account:

```bash
aws cloudformation deploy \
  --template-file deploy/aws/multi-account/spoke-role.yaml \
  --stack-name Argus-Spoke \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides HubAccountId=<hub-account-id>
```

Create `accounts.yaml` (see `accounts.yaml.example`) and set `ACCOUNTS_CONFIG` in the Lambda environment.

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

Set `AI_PROVIDER=anthropic\|bedrock` in `.env` or the Lambda environment.

---

## Multi-account setup

Create `accounts.yaml`:

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

Then run:

```bash
python main.py --cloud aws --run-now --accounts accounts.yaml
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

## Running tests

```bash
# All 187 tests — no cloud credentials needed
pytest tests/ -v

# Just AWS adapter tests
pytest tests/adapters/aws/ -v

# With coverage
pytest tests/ --cov=. --cov-report=term-missing
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
│   └── reports/           # Report generator + Slack delivery
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
│   ├── cli.py             # python main.py --cloud aws --run-now
│   ├── aws_lambda.py      # AWS Lambda handler
│   ├── gcp_cloudrun.py    # GCP Cloud Run Job handler
│   └── azure_function.py  # Azure Function timer trigger
├── deploy/
│   ├── aws/               # CloudFormation templates
│   ├── gcp/               # Cloud Run + Scheduler deploy script
│   └── azure/             # Bicep templates
└── tests/                 # 187 tests, all pass offline
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT
