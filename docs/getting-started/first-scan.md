# Your First Scan

What to expect from the output and how to interpret findings.

## What the agent does

Argus runs a **ReAct (Reason + Act) loop** — the AI reasons, calls a tool, observes the result, and repeats until it's confident the analysis is complete:

```
Iteration 1: list_resources → 47 billable resources discovered
Iteration 2: get_cost([all 47 IDs]) → cost data for every resource
Iteration 3: get_metrics(i-0abc123, days=90) → CPU 0.001%, NetworkIn 0 bytes, instance_type=m5.4xlarge
Iteration 4: get_last_activity(i-0abc123) → null (no CloudTrail events in 90 days)
Iteration 5: get_metrics(nat-0def456, days=90) → BytesOut 0
Iteration 6: get_last_activity(nat-0def456) → 2026-01-14T09:12:00Z (5 months ago)
...
Iteration N: submit_findings([...]) → done
```

## Reading the Slack output

The Slack message is a **compact digest** — it gives you the headline numbers and top findings at a glance, without flooding the channel with AI reasoning text.

```
Argus — AWS Waste Report (2026-06-17)

💸 $340.50/month estimated waste   📊 12 idle resources across 3 accounts

Two stopped EC2 instances and a forgotten NAT Gateway account for 72% of
total waste. Four RDS databases have had zero connections in over 30 days.

Top findings
🔴  prod-api-server (i-0abc123def)  ·  EC2 t3.xlarge    ·  $142.70/mo
🔴  nat-0def456abc                  ·  NAT Gateway       ·  $104.80/mo
🟡  staging-rds-cluster             ·  RDS db.r6g.large  ·  $48.20/mo
🟡  3 unattached volumes            ·  EBS gp3           ·  $24.00/mo
🟢  + 8 more findings in full report                     ·  $20.80/mo

[ 📄 Full report (HTML) ]   [ vamshisiddarth/argus ]
```

### Full HTML report

Click **Full report (HTML)** to open the self-contained report in your browser. It includes:

| Column | Description |
|--------|-------------|
| **Priority** | `HIGH` / `MEDIUM` / `LOW` — based on cost and confidence of idleness |
| **Resource** | Name and resource ID |
| **Type** | EC2 instance, RDS DB, NAT Gateway, etc. |
| **Region** | Cloud region |
| **Cost / mo** | Estimated USD/month from Cost Explorer / BigQuery / Cost Management |
| **Last activity** | Days since last CloudTrail / Audit Log / Activity Log event |

Click any row to expand the full AI reasoning: **Why idle** and **Recommendation** (specific action — delete, downsize, snapshot-and-delete, tag for review).

The HTML file is filterable by priority and resource type, sortable by cost, and works offline. It is generated after every scan and stored in S3 / GCS / Azure Blob (requires `REPORT_S3_BUCKET` / `REPORT_GCS_BUCKET` / `REPORT_STORAGE_ACCOUNT` to be set).

## Priority rules

| Priority | Condition |
|----------|-----------|
| **HIGH** | Confirmed idle AND cost > $20/month |
| **MEDIUM** | Likely idle OR cost $5–$20/month |
| **LOW** | Possibly idle OR cost < $5/month |

## Cost data caveats

!!! warning "Cost Explorer requires activation"
    `GetCostAndUsageWithResources` requires:

    1. Cost Explorer **activated** for your account (first activation takes up to 24 hours)
    2. **Resource-level data** enabled: AWS Console → Cost Management → Preferences → Resource-level data

    If not set up, cost fields show `$0.00` and Argus logs a warning with the setup URL.
    The agent will still flag idle resources based on metrics and activity signals alone.

## What Argus does NOT do

- **It never deletes or modifies resources.** It only reads.
- **It does not send alerts in real time.** It runs on a schedule (weekly by default).
- **It does not apply auto-remediation.** Every recommendation requires a human action.

## Typical scan cost

| Account size (raw) | After filters | AI context | Duration | Anthropic API | Bedrock | Vertex AI | Azure OpenAI |
|--------------------|--------------|-----------|----------|---------------|---------|-----------|--------------|
| ~50 resources | ~20 billable | top 20 | 2–4 min | ~$0.10 | ~$0.09 | ~$0.04 | ~$0.07 |
| ~500 resources | ~150 billable | top 150 | 5–10 min | ~$0.25 | ~$0.23 | ~$0.12 | ~$0.23 |
| ~5K resources | ~1,500 billable | top 200 (capped) | 5–10 min | ~$0.30 | ~$0.27 | ~$0.15 | ~$0.29 |
| ~50K resources | ~15K billable | top 200 (capped) | 5–10 min | ~$0.30 | ~$0.27 | ~$0.15 | ~$0.29 |

**Key point**: cost does not scale linearly with account size.

The two-phase scan architecture means:

1. **Phase 0** (no AI tokens): discover all resources → batch-fetch costs → sort by cost → keep top 200
2. **Phase 1** (AI loop): agent only ever sees ≤200 resources regardless of account size

This bounds both cost and latency for any account size. Set `MAX_RESOURCES_PER_SCAN` higher if you want to investigate more candidates (at proportionally higher AI cost).

**Pricing basis** (figures above are AI token cost only — excludes cloud API calls which are negligible):

| Provider | Model | Input | Output |
|----------|-------|-------|--------|
| Anthropic API | claude-sonnet-4-6 | $3.00/MTok | $15.00/MTok |
| AWS Bedrock | claude-sonnet-4-6 | $3.00/MTok | $15.00/MTok |
| Vertex AI | Gemini 1.5 Pro | $1.25/MTok | $5.00/MTok |
| Azure OpenAI | GPT-4o | $2.50/MTok | $10.00/MTok |

Vertex AI (Gemini 1.5 Pro) is the cheapest option at roughly half the Anthropic API cost.
Bedrock and Anthropic API use the same model at the same price — Bedrock saves on egress
if you're already running in AWS. Prompt caching (where supported) reduces input costs by ~10–30%.

!!! warning "Cost data gaps affect ranking"
    Phase 0 sorting relies on Cost Explorer / Billing API data. If cost data is unavailable,
    all costs show as $0.00 and resources are passed to the AI in discovery order rather
    than cost order. The AI still investigates them — it just has less signal for
    prioritization. Enabling cost data improves both accuracy and ordering.
