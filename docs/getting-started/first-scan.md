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
🔴  `prod-api-server` · EC2 Instance · $142.70/mo
🔴  `nat-0def456abc` · NAT Gateway · $104.80/mo
🟡  `staging-rds-cluster` · RDS Instance · $48.20/mo
🟡  `vol-0aa11bb22` · EBS Volume · $8.00/mo
🟢  `vol-0cc33dd44` · EBS Volume · $4.00/mo
⚪  +7 more findings in the full report

[ 📄 Full report (HTML) ]   [ vamshisiddarth/argus ]
```

### Decision board

Click **Full report (HTML)** to open the decision board in your browser. It groups findings into opportunities, each with:

- a savings range, split by billed, list price and model estimate
- a risk line, the evidence and check-first steps
- the member resources, with owner tags
- Approve / Investigate / Keep, with owner, note and keep-until

A "Read before deciding" banner at the top lists anything that limits the scan: failed accounts, preflight warnings, truncated coverage, incomplete discovery and metrics lost to throttling. See [Decision board](../concepts/board-report.md).

The page works offline. It is generated after every scan and stored in S3 / GCS / Azure Blob (requires `REPORT_S3_BUCKET` / `REPORT_GCS_BUCKET` / `REPORT_STORAGE_ACCOUNT` to be set).

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

    If not set up, cost fields show `$0.00` and Argus logs a warning pointing to the Preferences setting above.
    The agent will still flag idle resources based on metrics and activity signals alone.

## What Argus does NOT do

- **It never deletes or modifies resources.** It only reads.
- **It does not send alerts in real time.** It runs on a schedule (weekly by default).
- **It does not apply auto-remediation.** Every recommendation requires a human action.

## Scan cost

Model cost grows with the number of resources sent to the model, so it is capped, not fixed.

- **Measured:** one full run on a single account (1,614 resources analysed, Bedrock, a Sonnet-class model) took about 12 to 13 minutes and cost about $1.4 to $1.55, roughly $0.85 per 1,000 resources. One account is not a benchmark; your figure depends on the model, the resource mix and how many resources the rules already settle.
- **Capped:** `LLM_BUDGET_USD` defaults to $2.00. Without `MAX_RESOURCES_PER_SCAN`, the number of resources sent to the model follows the budget (about 150 per dollar, so 300 at the default). Raise the budget to cover more.
- **Shown before spending:** the plan line says how many resources fit the budget and the estimate. Run with `--strict-coverage` to stop before any model call if the budget cannot cover everything. If a run would overspend, it stops before the batch that does and keeps what it found.
- **Cheaper:** deterministic rules (idle NAT gateways and load balancers, unattached volumes, unassociated Elastic IPs, stopped instances) cost no model tokens and are removed from the model's list.

The figures cover model tokens only. Cloud API calls are small, but AWS charges for Cost Explorer API requests in the account being scanned.

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

!!! warning "Without resource-level cost data there is no billed dollar"
    If Cost Explorer resource-level data is not enabled (preflight check P8), findings carry no billed cost. Rule findings use list prices and the model's figures are estimates, so the headline reads "unverified waste estimate" and is not a savings figure. Candidates are then ordered by list price and idleness instead of billed cost.
