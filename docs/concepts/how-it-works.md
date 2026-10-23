# How It Works

## :material-sitemap: Architecture

Argus follows a clean separation of concerns called **Same brain. Different hands. Different home.**

```
┌─────────────────────────────────────────────────────────────────┐
│  core/  — Pure Python, zero cloud imports                       │
│                                                                 │
│  AgentLoop.run()  (scan pipeline, the default engine)           │
│   ├── Discover: adapter.list_resources() + costs                │
│   ├── Decide by rule: idle NAT / ALB, unattached volumes, ...   │
│   ├── Gather evidence in code: metrics, config, last activity   │
│   └── Triage: batched, stateless model calls -> findings        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
     CloudAdapter          AIProvider         Entrypoint
     (AWS/GCP/Azure)   (Bedrock/Anthropic   (Lambda/CloudRun/
                        /Vertex/AzureOAI)    AzureFunction)
```

**Brain** = `core/` — the agent loop and prompts. No cloud imports. Runs in any environment.

**Hands** = `adapters/` — cloud-specific data collection. Implements a four-method contract.

**Home** = `entrypoints/` — thin runtime wrappers. No business logic.

## :material-pipe: The scan pipeline

A scan runs in five steps. Everything that is a fact is gathered in code; the model only judges.

1. **Discover.** The adapter lists resources. On AWS, Resource Explorer types such as `ec2:natgateway` are mapped to the registry's ids, and free configuration objects (security-group rules, subnets, IAM roles, task definitions, ...) are skipped on purpose and counted in `coverage.free_config_skipped`.
2. **Decide by rule.** [Baseline rules](baseline-rules.md) flag the unambiguous cases (idle NAT gateways and load balancers from metrics; unattached volumes, unassociated Elastic IPs and stopped instances from configuration). They run over every resource, are priced from a list-price catalog, and win over the model.
3. **Gather evidence.** For every remaining resource Argus collects metrics (over the configured window), cost, configuration, and, where metrics could not decide, last activity. Missing data stays missing; it is never turned into zero.
4. **Triage.** Resources are ranked (billed cost, high-impact types first) and sent to the model in batches. Each batch is one stateless call, so spend grows linearly with the number of resources. Before the first call Argus estimates the cost; it stops before a batch that would overspend the budget and keeps everything found so far.
5. **Report.** Findings carry their evidence, `confidence`, `cost_basis` and `detected_by`. The summary is generated from the findings, not by another model call.

`ARGUS_ENGINE=react` switches back to the original tool-calling loop described below, which also powers `argus chat`.

## :material-recycle: The ReAct loop (chat and the `react` engine)

Argus uses **ReAct (Reason + Act)** — a pattern where the AI alternates between reasoning and tool use.

Before the AI sees anything, a **Phase 0** step runs without AI tokens: it discovers all resources, drops
non-billable types and anything matching `EXCLUDE_TAGS` / `EXCLUDE_RESOURCE_TYPES`, fetches cost for all of
them in one batched call, sorts by cost, and keeps the top `MAX_RESOURCES_PER_SCAN` (default 200). The AI's
first `list_resources` call returns that pre-sorted list with `cost_usd` already attached.

```
User:      "Begin your cloud cost analysis now."

Claude:    <thinks> I'll start by listing all resources.
           <calls>  list_resources()

Tool:      [{"id":"i-0abc","type":"AWS::EC2::Instance","region":"us-east-1","cost_usd":28.4},
            {"id":"nat-0def","type":"AWS::EC2::NatGateway","region":"us-east-1","cost_usd":10.8},
            ...]   # already sorted by cost, capped at 200

Claude:    <thinks> i-0abc costs $28.40/month. Let me check if it's actually being used.
           <calls>  get_metrics(resource_id="i-0abc", resource_type="AWS::EC2::Instance")
                    get_last_activity(resource_id="i-0abc", resource_type="AWS::EC2::Instance")

Tool:      {"has_data": true, "CPUUtilization_avg": 0.0014, "NetworkIn_avg": 0.0}
           null

Claude:    <thinks> No CloudTrail events in 90 days + near-zero metrics = idle.
           ... investigates more resources ...
           <calls>  submit_findings([...])
```

When the AI requests several tools in one turn, they run in parallel. The loop runs for up to
`MAX_AGENT_ITERATIONS` (default 50) and stops early if the scan's `LLM_BUDGET_USD` is reached.

## :material-hammer-wrench: Tool dispatch

`AgentLoop._execute()` maps tool names to adapter calls. Only these five tools are allowed; anything else is rejected before execution:

| Tool                | Adapter method                                          | Returns                                        |
| ------------------- | ------------------------------------------------------- | ---------------------------------------------- |
| `list_resources`    | _(Phase 0 result, cached)_                              | Top resources by cost, compact JSON with `cost_usd` |
| `get_metrics`       | `adapter.get_metrics(resource_id, resource_type, days)` | `MetricSummary` (avg values + `has_data` flag) |
| `get_cost`          | `adapter.get_cost(resource_ids, days)`                  | `dict[resource_id, float]` (USD)               |
| `get_last_activity` | `adapter.get_last_activity(resource_id, resource_type)` | ISO8601 timestamp or `null`                    |
| `submit_findings`   | _(none — ends the loop)_                                | Structured findings for the report             |

## :material-speedometer: Token optimization

Three mechanisms keep AI token usage low:

1. **Non-billable resource filter** — IAM roles, subnets, route tables, CloudFormation stacks, etc. are stripped before the AI sees `list_resources`. Cuts 60–70% of resources in a typical account.
2. **Compact JSON** — resource list uses short keys (`id`, `type`, `region`) and omits null fields. No whitespace in serialized JSON.
3. **Prompt caching** (Anthropic API provider) — the system prompt is pinned with `cache_control: ephemeral`, so iterations 2–N are billed at the cached-read rate for that portion.

## :material-chart-timeline-variant: Finding lifecycle

```
Resource Explorer / Asset Inventory / Resource Graph
        ↓ filter non-billable + EXCLUDE_TAGS / EXCLUDE_RESOURCE_TYPES
get_cost (Phase 0, one batched call, no AI tokens)
        ↓ sort by cost, keep top MAX_RESOURCES_PER_SCAN
AI sees list_resources result (compact JSON with cost_usd)
        ↓ AI prioritizes expensive candidates
get_metrics + get_last_activity (per candidate, parallel)
        ↓ AI reasons: idle? underutilized? orphaned?
submit_findings
        ↓
ResourceFinding dataclass list
        ↓
build_report() → JSON report (+ scan_diff vs previous scan)
        ↓
build_html_report() → self-contained HTML file
        ↓ (if REPORT_S3_BUCKET / REPORT_GCS_BUCKET / REPORT_STORAGE_ACCOUNT is set)
upload to S3 / GCS / Azure Blob → pre-signed / SAS URL
        ↓ (if REMEDIATION_ENABLED=true)
run_remediation() → Jira tickets for policy matches
        ↓
build notification payload
        ↓
notify_all() → delivers to each channel in NOTIFICATION_PROVIDER
```
