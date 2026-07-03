# Argus — Architecture

## Design Philosophy

> **Same brain. Different hands. Different home.**
>
> The agent loop and AI reasoning are pure Python with zero cloud imports.
> Cloud adapters are swappable. The runtime host (Lambda / Cloud Run / Azure Function) is swappable.
> Deploying on a new cloud means writing one adapter — nothing else changes.

---

## High-Level System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TRIGGER (weekly cron — platform-native per cloud)                          │
│                                                                             │
│  AWS: EventBridge Rule          GCP: Cloud Scheduler       Azure: Timer     │
│          │                              │                    Trigger │      │
│          └──────────────────────────────┴────────────────────────────┘      │
│                                         │                                   │
│                                         ▼                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  ENTRYPOINT (thin runtime wrapper — no business logic)               │   │
│  │  aws_lambda.py / gcp_cloudrun.py / azure_function.py / cli.py        │   │
│  └───────────────────────────────┬──────────────────────────────────────┘   │
│                                  │                                          │
│                                  ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  CORE — pure Python, zero cloud imports                              │   │
│  │                                                                      │   │
│  │  ┌─────────────────────────────────────────────────────────────┐     │   │
│  │  │  AGENT LOOP  (core/agent/loop.py)                           │     │   │
│  │  │                                                             │     │   │
│  │  │  System prompt injected with:                               │     │   │
│  │  │  - cloud type (aws / gcp / azure)                           │     │   │
│  │  │  - account list + regions                                   │     │   │
│  │  │  - available tools                                          │     │   │
│  │  │                                                             │     │   │
│  │  │   ┌─────────┐    ┌──────────────┐    ┌──────────────────┐   │     │   │
│  │  │   │  THINK  │───►│   CALL TOOL  │───►│  OBSERVE RESULT  │   │     │   │
│  │  │   └────▲────┘    └──────────────┘    └────────┬─────────┘   │     │   │
│  │  │        │                                       │            │     │   │
│  │  │        └───────────────────────────────────────┘            │     │   │
│  │  │                    (repeat until done)                      │     │   │
│  │  └─────────────────────────────────────────────────────────────┘     │   │
│  │                                                                      │   │
│  │  ┌──────────────────────┐   ┌───────────────────────────────────┐    │   │
│  │  │  REPORT GENERATOR    │   │  NOTIFICATIONS                    │    │   │
│  │  │  core/reports/       │   │  core/reports/delivery.py         │    │   │
│  │  │  - JSON/HTML/PDF/    │   │  - Slack / Teams / generic webhook│    │   │
│  │  │    PPTX export       │   │  - ranked by monthly waste ($)    │    │   │
│  │  └──────────────────────┘   └───────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## The Adapter Pattern — How Multi-Cloud Works

```
  AGENT LOOP calls these 4 methods only. Never raw cloud SDKs.
  ┌───────────────────────────────────────────────────────────────┐
  │  CloudAdapter (adapters/base.py)                              │
  │                                                               │
  │  list_resources(regions)     → list[Resource]                 │
  │  get_metrics(resource_id, days) → MetricSummary               │
  │  get_cost(resource_ids, days)   → dict[str, float]            │
  │  get_last_activity(resource_id) → datetime | None             │
  └───────────────────────┬───────────────────────────────────────┘
                          │  implemented by
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │ AWS Adapter  │ │ GCP Adapter  │ │Azure Adapter │
  │              │ │              │ │              │
  │ Resource     │ │ Asset        │ │ Resource     │
  │ Explorer     │ │ Inventory    │ │ Graph        │
  │              │ │              │ │              │
  │ CloudWatch   │ │ Cloud        │ │ Azure        │
  │ GetMetricData│ │ Monitoring   │ │ Monitor      │
  │              │ │              │ │              │
  │ Cost         │ │ BigQuery     │ │ Cost         │
  │ Explorer     │ │ billing exp. │ │ Management   │
  │              │ │              │ │              │
  │ CloudTrail   │ │ Cloud Audit  │ │ Activity     │
  │ LookupEvents │ │ Logs         │ │ Log          │
  └──────────────┘ └──────────────┘ └──────────────┘
```

---

## The AI Provider Pattern — Pluggable Intelligence

```
  AGENT LOOP calls one method. Never raw model SDKs.
  ┌───────────────────────────────────────────────────────────────┐
  │  AIProvider (ai/base.py)                                      │
  │                                                               │
  │  chat(messages, tools) → AIResponse                           │
  └───────────────────────┬───────────────────────────────────────┘
                          │  implemented by
          ┌───────────────┼───────────────┬───────────────┐
          ▼               ▼               ▼               ▼
  ┌─────────────┐ ┌─────────────┐ ┌────────────┐ ┌────────────────┐
  │  Bedrock    │ │  Vertex AI  │ │Azure OpenAI│ │ Anthropic API  │
  │  ✅ built   │ │  ✅ built    │ │  ✅ built  │ │ ✅ built       │
  │  (AWS)      │ │  (GCP)      │ │  (Azure)   │ │ (local dev /   │
  │             │ │             │ │            │ │  any cloud)    │
  │ Claude      │ │ Gemini 1.5  │ │  GPT-4o    │ │ Claude         │
  │ Sonnet 4.6  │ │ Pro         │ │            │ │ Sonnet 4.6     │
  └─────────────┘ └─────────────┘ └────────────┘ └────────────────┘

  AI_PROVIDER env var selects which one loads at runtime.
  Anthropic API works on any cloud — best for local dev.
```

---

## AWS Deployment — Single Account

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  USER ACTION: click "Launch Stack" in README                     │
  │                    │                                             │
  │                    ▼                                             │
  │  SAM (deploy/aws/single-account/template.yaml) creates:          │
  │                                                                  │
  │  ┌──────────────┐  ┌───────────────┐  ┌────────────────────┐     │
  │  │  Lambda Fn   │  │  EventBridge  │  │  IAM Role          │     │
  │  │  (Argus      │◄─│  Rule         │  │  (read-only:       │     │
  │  │   agent)     │  │  cron:        │  │  Resource Explorer │     │
  │  │              │  │  0 8 * * 1    │  │  CloudWatch        │     │
  │  └──────┬───────┘  └───────────────┘  │  Cost Explorer     │     │
  │         │                             │  CloudTrail        │     │
  │         │ uses                        │  Bedrock           │     │
  │         │                             └────────────────────┘     │
  │         ▼                                                        │
  │  ┌──────────────────────────────────────┐                        │
  │  │  AWS APIs (same account)             │                        │
  │  │  Resource Explorer → all resources   │                        │
  │  │  CloudWatch        → metrics         │                        │
  │  │  Cost Explorer     → cost data       │                        │
  │  │  CloudTrail        → last activity   │                        │
  │  └──────────────────────────────────────┘                        │
  │         │                                                        │
  │         ▼                                                        │
  │  ┌──────────────┐   ┌────────────────┐                           │
  │  │  S3 Bucket   │   │  Slack Webhook │                           │
  │  │  (JSON report│   │  (summary +    │                           │
  │  │   archive)   │   │   top findings)│                           │
  │  └──────────────┘   └────────────────┘                           │
  └──────────────────────────────────────────────────────────────────┘
```

---

## AWS Deployment — Multi-Account (Hub + Spoke)

```
  ┌────────────────────────────────────────────────────────────────────┐
  │  HUB ACCOUNT (Argus runs here)                                     │
  │                                                                    │
  │  SAM: deploy/aws/multi-account/hub/template.yaml                   │
  │                                                                    │
  │  EventBridge ──► Lambda (Argus)                                    │
  │                     │                                              │
  │                     │  reads accounts.yaml                         │
  │                     │  for each account:                           │
  │                     │                                              │
  │     ┌───────────────┼───────────────────┐                          │
  │     │               │                   │                          │
  │     ▼               ▼                   ▼                          │
  │  STS AssumeRole  STS AssumeRole     STS AssumeRole                 │
  │     │               │                   │                          │
  └─────┼───────────────┼───────────────────┼──────────────────────────┘
        │               │                   │
        ▼               ▼                   ▼
  ┌───────────┐   ┌───────────┐      ┌───────────┐
  │  Account  │   │  Account  │      │  Account  │
  │   dev     │   │  staging  │  ... │   prod    │
  │           │   │           │      │           │
  │ IAM Role: │   │ IAM Role: │      │ IAM Role: │
  │ Argus     │   │ Argus     │      │ Argus     │
  │ SpokeRole │   │ SpokeRole │      │ SpokeRole │
  │           │   │           │      │           │
  │ Trust:    │   │ Trust:    │      │ Trust:    │
  │ hub acct  │   │ hub acct  │      │ hub acct  │
  │ Lambda    │   │ Lambda    │      │ Lambda    │
  └───────────┘   └───────────┘      └───────────┘

  Spoke role deployed via:
  CloudFormation: deploy/aws/multi-account/spoke-role.yaml
  (tiny template — one IAM role + trust policy)

  Credentials: temporary STS sessions, auto-expire in 1 hour, never stored.
```

---

## GCP Deployment

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  GCP PROJECT                                                     │
  │                                                                  │
  │  deploy/gcp/deploy.sh (gcloud CLI)                               │
  │                                                                  │
  │  Cloud Scheduler ──► Cloud Run Job (Argus)                       │
  │  (weekly cron)            │                                      │
  │                           │                                      │
  │                ┌──────────┼──────────┐                           │
  │                ▼          ▼          ▼                           │
  │          Asset        Cloud       BigQuery                       │
  │          Inventory    Monitoring  (billing                       │
  │          (resources)  (metrics)   export)                        │
  │                           │                                      │
  │                    Vertex AI (Gemini) or Anthropic API           │
  │                           │                                      │
  │                    Slack / Teams / Webhook (+ GCS report)        │
  └──────────────────────────────────────────────────────────────────┘
```

---

## Azure Deployment

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  AZURE SUBSCRIPTION                                              │
  │                                                                  │
  │  deploy/azure/function-app.bicep                                 │
  │                                                                  │
  │  Timer Trigger ──► Azure Function (Argus)                        │
  │  (weekly cron)         │                                         │
  │                        │                                         │
  │             ┌──────────┼──────────┐                              │
  │             ▼          ▼          ▼                              │
  │       Resource      Azure       Cost                             │
  │       Graph         Monitor     Management                       │
  │       (resources)   (metrics)   (cost)                           │
  │                        │                                         │
  │                 Azure OpenAI (GPT-4o) or Anthropic API           │
  │                        │                                         │
  │                 Slack / Teams / Webhook (+ Blob Storage report)  │
  └──────────────────────────────────────────────────────────────────┘
```

---

## The Agent's ReAct Loop — Step by Step

```
  INPUT: cloud adapter + AI provider + account list + regions
  │
  ▼
  Build system prompt
  (include: cloud type, account context, tool schemas, goal)
  │
  ▼
┌─────────────────────────────────────────────────────────────────┐
│  ITERATION START                                                │
│                                                                 │
│  Send conversation to AI provider                               │
│          │                                                      │
│          ▼                                                      │
│  AI responds with one of:                                       │
│    A) tool_call → { name: "list_resources", args: {...} }       │
│    B) text      → final analysis (loop ends)                    │
│          │                                                      │
│  if A:   │                                                      │
│          ▼                                                      │
│  Execute tool via CloudAdapter                                  │
│  (list_resources / get_metrics / get_cost / get_last_activity)  │
│          │                                                      │
│          ▼                                                      │
│  Append tool result to conversation                             │
│          │                                                      │
│          └──────────────────────► back to ITERATION START       │
│                                                                 │
│  if B:   │                                                      │
│          ▼                                                      │
│  Parse findings from AI text                                    │
│  Build ResourceFinding list                                     │
│  Generate JSON report                                           │
│  Send to Slack                                                  │
│  Save to cloud storage                                          │
│  DONE                                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow — ResourceFinding Lifecycle

```
  CloudAdapter.list_resources()
        │
        │  returns raw Resource objects (id, type, region, tags)
        ▼
  Agent loop feeds to AI as context
        │
        │  AI calls get_metrics(), get_cost(), get_last_activity()
        ▼
  AI synthesizes all signals and produces final analysis
        │
        │  "This NAT Gateway transferred 847 bytes in 14 days,
        │   costs $31.20/month, last configured 73 days ago.
        │   Owner tag: team=backend. Recommendation: delete."
        ▼
  ResourceFinding created (core/models/finding.py)
  (resource_id, resource_type, cloud, estimated_monthly_cost,
   waste_reason, recommendation, priority, tags, last_activity)
        │
        ▼
  ReportGenerator sorts findings by estimated_monthly_cost desc
        │
        ▼
  Reports saved to S3 / GCS / Azure Blob (JSON, HTML, PDF, PPTX)
        │
        ▼
  Notifications: Slack / Teams / generic webhook — executive summary + top N findings
```

---

## What Resource Explorer Returns (AWS)

Resource Explorer searches across all resource types in an account.
No per-type configuration needed — it finds everything.

```
  Sample output (simplified):
  [
    { type: "AWS::EC2::Instance",    id: "i-0abc123",  region: "us-east-1" },
    { type: "AWS::RDS::DBInstance",  id: "db-xyz",     region: "us-east-1" },
    { type: "AWS::ElasticLoadBalancingV2::LoadBalancer", id: "arn:...", region: "us-west-2" },
    { type: "AWS::EC2::NatGateway",  id: "nat-0def",   region: "us-east-1" },
    { type: "AWS::Lambda::Function", id: "my-fn",      region: "eu-west-1" },
    { type: "AWS::SQS::Queue",       id: "arn:...",    region: "us-east-1" },
    { type: "AWS::DynamoDB::Table",  id: "my-table",   region: "us-east-1" },
    ... (all resource types, all regions, all in one API call)
  ]

  The AI then decides which ones warrant metric investigation.
  We never hardcode which resource types to check.
```

---

## Notification Format (Slack example)

```
  ┌──────────────────────────────────────────────────────────────┐
  │  🔍 Argus Weekly Report — AWS Account: prod (444455...)      │
  │  Scanned 340 resources across 3 regions                      │
  │                                                              │
  │  💸 Estimated monthly waste: $487.30                         │
  │  📋 Idle resources found: 9                                  │
  │                                                              │
  │  Top findings:                                               │
  │                                                              │
  │  1. nat-0def456  NAT Gateway  us-east-1                      │
  │     Cost: $94.20/mo  |  Priority: HIGH                       │
  │     847 bytes transferred in 14 days. Last touched 73 days   │
  │     ago. Team: backend. → Delete or detach.                  │
  │                                                              │
  │  2. alb-abc123  Load Balancer  us-east-1                     │
  │     Cost: $47.10/mo  |  Priority: HIGH                       │
  │     0 requests in 30 days. No targets registered.            │
  │     → Delete the load balancer.                              │
  │                                                              │
  │  ... (up to 10 findings in Slack, full report in S3)         │
  │                                                              │
  │  📄 Full report: s3://argus-reports/2026-06-06.json          │
  └──────────────────────────────────────────────────────────────┘
```

---

## Why No Hardcoded Thresholds

Most cloud cost tools work like this: if CPU < 5% for 7 days, flag as idle. If network bytes < X, flag as idle. These rules are written by humans, per resource type, in advance.

The problem is that "idle" is context-dependent in ways a static rule cannot capture:

- A NAT Gateway moving 2 MB/day might be critical infrastructure for a VPN tunnel, or it might be orphaned. The bytes alone don't tell you.
- An RDS instance with 0 connections might be a reporting replica that runs once a month, or it might be forgotten from a migration two years ago. The connection count alone doesn't tell you.
- A Lambda function invoked 3 times in 30 days might be a monthly billing job, or it might be dead code. The invocation count alone doesn't tell you.

Tags, last activity, cost trend, resource name, account context, and the combination of signals together are what actually determine whether something is waste. Writing a rule that accounts for all of that, for every resource type, is the full-time job of a FinOps team.

Argus takes a different approach: give the AI the raw signals (metrics, cost, last activity, tags) and let it reason about idleness the same way a senior engineer would. The AI can weigh signals against each other, apply domain knowledge about what each resource type typically does, and explain its reasoning in plain language. No rules to write, no thresholds to tune per account.

The tradeoff is that the AI is not deterministic. Two scans of the same account might produce slightly different findings if resource states are borderline. We mitigate this by setting `temperature=0` and by prompting the AI to cite specific metrics in every finding, which makes its reasoning auditable.

---

## Why the 4-Method Adapter Contract

The adapter contract is deliberately minimal: `list_resources`, `get_metrics`, `get_cost`, `get_last_activity`. Four methods, that's it.

Several alternatives were considered and rejected:

**One method per resource type** (e.g., `list_ec2_instances`, `list_rds_instances`): the agent loop would need to know which methods to call for which cloud, defeating the point of abstraction. Adding a new resource type would require changes in core.

**Raw SDK access from core**: passing boto3/google.cloud/azure clients into the agent loop would make core/ untestable without real cloud credentials and would couple the reasoning logic to specific SDK versions.

**Richer contracts** (e.g., `get_idle_score`, `get_rightsizing_recommendation`): these push analysis logic into the adapter, which means duplicating it across three cloud implementations and hardcoding what "idle" means at the adapter layer. The whole point is that the AI does the analysis.

The 4-method contract keeps the boundary clean: adapters are responsible for fetching data, the agent loop is responsible for reasoning about it. A new cloud adapter needs no knowledge of how findings are structured or how the AI prompt is built. A change to the AI analysis needs no changes to any adapter.

The contract is also cheap to implement. The four methods map directly to the four cloud API categories every major cloud exposes: resource inventory, metrics, billing, and audit logs. Any cloud that exposes these four things can run Argus.

---

## Repository Structure — Contributor View

```
  Want to add a new cloud?
  └── Create adapters/<cloud>/adapter.py implementing the 4-method contract
  └── Create ai/<provider>.py implementing chat()
  └── Create entrypoints/<cloud>_<runtime>.py
  └── Create deploy/<cloud>/ with IaC template
  └── Zero changes to core/, zero changes to other adapters

  Want to improve the AI analysis?
  └── Edit core/agent/prompts.py — that's it

  Want to add a new report format?
  └── Edit core/reports/generator.py

  Tests need no cloud credentials:
  └── pytest tests/  runs entirely offline via moto + fixtures
```
