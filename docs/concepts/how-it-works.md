# How It Works

## :material-sitemap: Architecture

Argus follows a clean separation of concerns called **Same brain. Different hands. Different home.**

```
┌─────────────────────────────────────────────────────────────────┐
│  core/  — Pure Python, zero cloud imports                       │
│                                                                 │
│  AgentLoop.run()                                                │
│   ├── Think: ai_provider.chat(messages, tools, system_prompt)   │
│   ├── Act:   adapter.list_resources() / get_metrics() / ...     │
│   ├── Observe: tool result appended to conversation             │
│   └── Repeat until submit_findings()                            │
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

## :material-recycle: The ReAct loop

Argus uses **ReAct (Reason + Act)** — a pattern where the AI alternates between reasoning and tool use:

```
User:      "Begin your cloud cost analysis now."

Claude:    <thinks> I'll start by listing all resources.
           <calls>  list_resources()

Tool:      [{"id":"i-0abc","type":"AWS::EC2::Instance","region":"us-east-1"},
            {"id":"nat-0def","type":"AWS::EC2::NatGateway","region":"us-east-1"},
            ...]

Claude:    <thinks> I see 47 resources. Let me get cost data for all of them at once.
           <calls>  get_cost(resource_ids=[...all 47...])

Tool:      {"i-0abc": 28.40, "nat-0def": 10.80, ...}

Claude:    <thinks> i-0abc costs $28.40/month. Let me check if it's actually being used.
           <calls>  get_metrics(resource_id="i-0abc", resource_type="AWS::EC2::Instance")

Tool:      {"has_data": true, "CPUUtilization_avg": 0.0014, "NetworkIn_avg": 0.0}

Claude:    <thinks> 0.001% CPU — effectively zero. Let me check last activity.
           <calls>  get_last_activity(resource_id="i-0abc", resource_type="AWS::EC2::Instance")

Tool:      null

Claude:    <thinks> No CloudTrail events in 90 days + near-zero metrics = idle.
           ... investigates more resources ...
           <calls>  submit_findings([...])
```

The loop runs for up to 50 iterations. In practice, a full scan of 50 resources takes 8–15 iterations.

## :material-hammer-wrench: Tool dispatch

`AgentLoop._execute()` maps tool names to adapter calls:

| Tool                | Adapter method                                          | Returns                                        |
| ------------------- | ------------------------------------------------------- | ---------------------------------------------- |
| `list_resources`    | `adapter.list_resources(ignore_regions)`                | List of `Resource` objects (compact JSON)      |
| `get_metrics`       | `adapter.get_metrics(resource_id, resource_type, days)` | `MetricSummary` (avg values + `has_data` flag) |
| `get_cost`          | `adapter.get_cost(resource_ids, days)`                  | `dict[resource_id, float]` (USD)               |
| `get_last_activity` | `adapter.get_last_activity(resource_id, resource_type)` | ISO8601 timestamp or `null`                    |

## :material-speedometer: Token optimization

Three mechanisms keep AI token usage low:

1. **Non-billable resource filter** — IAM roles, subnets, route tables, CloudFormation stacks, etc. are stripped before the AI sees `list_resources`. Cuts 60–70% of resources in a typical account.
2. **Compact JSON** — resource list uses short keys (`id`, `type`, `region`) and omits null fields. No whitespace in serialized JSON.
3. **Prompt caching** — the system prompt is pinned with `cache_control: ephemeral`. Iterations 2–N pay 10% of normal input token cost for the cached portion.

## :material-chart-timeline-variant: Finding lifecycle

```
Resource Explorer / Asset Inventory / Resource Graph
        ↓ filter non-billable
        ↓ compact JSON
AI sees list_resources result
        ↓ AI selects candidates by cost
get_cost (batched — one API call)
        ↓ AI prioritizes expensive candidates
get_metrics + get_last_activity (per candidate)
        ↓ AI reasons: idle? underutilized? orphaned?
submit_findings
        ↓
ResourceFinding dataclass list
        ↓
build_report() → JSON report
        ↓
build_html_report() → self-contained HTML file
        ↓ (if REPORT_*_BUCKET is set)
upload to S3 / GCS / Azure Blob → pre-signed / SAS URL
        ↓
build notification payloads (Slack / Teams / generic webhook)
        ↓
notify_all() → delivers to all configured channels
```
