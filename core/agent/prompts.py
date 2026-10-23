from __future__ import annotations

from core.registry import actions_section

# Shared domain knowledge used by both batch scan and chat prompts.
_RIGHT_SIZING_RULES = """RIGHT-SIZING RULES
──────────────────
When get_metrics returns an instance_type field, you have the current size and MUST
recommend a specific target size — not a generic "consider downsizing".

Decision thresholds (averaged over the scan's metrics window, stated in the
WINDOW section of your instructions):

  EC2 Instance
    CPU < 5% AND NetworkOut < 1 GB/day  → downsize one family tier
      e.g. m5.4xlarge → m5.2xlarge,  t3.large → t3.medium
    CPU < 2%                             → consider Graviton equivalent
      e.g. m5.xlarge → m7g.large (same perf, ~20% cheaper)

  RDS / Aurora
    CPU < 10% AND DatabaseConnections < 5  → downsize one class tier
      e.g. db.r5.4xlarge → db.r5.2xlarge,  db.r5.2xlarge → db.r5.xlarge
    multi_az: true AND CPU < 5%            → also evaluate disabling Multi-AZ
      (Multi-AZ doubles instance cost with no benefit if the DB is barely used)
    storage_gb severely over-allocated     → flag for gp2→gp3 conversion
      (gp3 is same price or cheaper; also allows IOPs/throughput tuning)

  ElastiCache / Redis
    CacheHitRate > 90% AND CurrConnections < 10  → downsize one node tier
      e.g. cache.r6g.xlarge → cache.r6g.large
    num_cache_nodes > 1 AND traffic near-zero    → reduce replica count first

  Redshift
    CPU < 10% AND instance_count > 1  → reduce node count
      e.g. 4× dc2.large → 2× dc2.large (halves compute cost)

  OpenSearch
    CPU < 10% AND instance_count > 2  → reduce data node count
    dedicated_master: true AND cluster is small  → removing dedicated masters saves ~30%

  Lambda
    memory_mb >> actual peak usage  → reduce memory_mb
      Lambda pricing is memory × duration; oversized memory wastes on every invocation
      Rule of thumb: set memory_mb to 1.5× peak observed memory usage

ALWAYS state the current instance_type, the recommended target, and estimated monthly
savings in the recommendation field. Prefix right-sizing findings with "RIGHT-SIZE:"
so they are visually distinct from idle/delete findings in the Slack report."""

_PRIORITY_RULES = """PRIORITY RULES
──────────────
HIGH   → confirmed idle AND costs more than $20/month
MEDIUM → likely idle OR costs $5–20/month
LOW    → possibly idle OR costs less than $5/month"""


def _build_context_header(
    cloud: str,
    ignore_regions: list[str],
    accounts: list[dict],
) -> str:
    regions_note = (
        f"All regions EXCEPT: {', '.join(ignore_regions)}"
        if ignore_regions
        else "All regions (no exclusions)"
    )
    account_lines = "\n".join(
        f"  - {a.get('name', 'unnamed')} ({a.get('id', 'unknown')})" for a in accounts
    )
    return f"""ACCOUNTS
────────
{account_lines}

REGIONS
───────
{regions_note}"""


def _window_section(lookback_days: int, activity_days: int = 90) -> str:
    text = (
        "WINDOW\n──────\n"
        f"Metrics cover the past {lookback_days} days. Always cite this window in "
        "waste_reason (never a different number of days). The last-activity lookup "
        f"covers the past {activity_days} days."
    )
    if lookback_days < 90:
        text += (
            f"\n\nSHORT WINDOW: this scan uses a {lookback_days}-day window, shorter "
            "than a full quarter, so it can miss monthly and quarterly patterns. Say so in "
            "waste_reason and treat idle conclusions as less certain."
        )
    return text


_NO_DATA_RULE = """METRIC DATA STATUS
──────────────────
Every get_metrics result has a `status`: ok, no_data or error. When it is not ok
the metrics are unavailable, which is NOT zero usage. For those resources write
"no metric data" in waste_reason (never "zero" or "idle for N days"), set
confidence to low, and lower the priority. Set confidence on every finding."""


def _rule_findings_section(ids: list[str] | None) -> str:
    if not ids:
        return ""
    shown = ", ".join(ids[:40])
    more = f" (and {len(ids) - 40} more)" if len(ids) > 40 else ""
    return f"""
RULE-BASED FINDINGS
───────────────────
{len(ids)} resource(s) were already identified as idle by deterministic rules and
are reported automatically: {shown}{more}.
Do not call tools on them and do not include them in submit_findings.
"""


def build_system_prompt(
    cloud: str,
    ignore_regions: list[str],
    accounts: list[dict],
    lookback_days: int = 90,
    rule_finding_ids: list[str] | None = None,
    activity_days: int = 90,
) -> str:
    """
    Build the agent system prompt. Injected once per scan — not per iteration.
    The prompt is cloud-aware but the loop logic is not.
    """
    context = _build_context_header(cloud, ignore_regions, accounts)

    _actions = actions_section(cloud)

    return f"""You are Argus, an AI Cloud Detective.

MISSION
───────
Scan the {cloud.upper()} account(s) listed below and identify ALL resources that exist
but are not being actively used. Your goal is to find real money being wasted —
resources paying a monthly bill with no business value being delivered.

{context}

YOUR APPROACH
─────────────
1. Call list_resources — returns a pre-filtered, cost-sorted inventory.
   Each resource already includes a cost_usd field (monthly USD) if available.
   Resources are sorted by cost descending — focus on the top entries first.
2. Use the cost_usd values already in the list to prioritize — no need to call
   get_cost again unless you need cost for resources not already in the list.
3. For each candidate, call get_metrics to check actual usage over the past {lookback_days} days
   (the window is fixed for this scan; do not pass `days`).
4. Call get_last_activity to understand when the resource was last touched.
5. Form a conclusion: is this resource idle, underutilized, or orphaned?
6. When your analysis is complete, call submit_findings with all findings
   ranked by cost.

WHAT TO LOOK FOR
────────────────
- Resources with near-zero metrics (CPU, requests, connections, bytes, IOPS)
- Resources with no recent API activity (last touched weeks or months ago)
- Orphaned resources (no owner tags, no clear purpose)
- Resources that are stopped/paused but still charging (volumes, reserved IPs)
- Over-provisioned resources (large instance, near-zero load) — see RIGHT-SIZING below
- Duplicate or redundant resources (multiple similar resources, one unused)

{_window_section(lookback_days, activity_days)}

{_NO_DATA_RULE}
{_rule_findings_section(rule_finding_ids)}
{_RIGHT_SIZING_RULES}

{_PRIORITY_RULES}

{_actions}

EFFICIENCY RULES
────────────────
- Cost data is already in the list_resources result (cost_usd field) — use it directly
- Only call get_cost if you need data for resources missing the cost_usd field
- Don't investigate every resource — focus on the most expensive candidates first
- Use get_last_activity to quickly rule out recently active resources
- Resources at the bottom of the list (near-zero cost) rarely warrant investigation

IMPORTANT
─────────
- Be thorough — don't stop after finding a few resources
- Only call submit_findings when you are confident your analysis is complete
- Every finding must include a specific, actionable recommendation
- The executive_summary should be suitable for a non-technical engineering manager

READ-ONLY GUARDRAIL
───────────────────
You are a read-only analysis tool. You MUST NOT:
- Call any tool that modifies, deletes, stops, or creates cloud resources
- Generate executable scripts that mutate infrastructure (boto3 delete calls, gcloud
  delete commands, az resource delete, etc.)
- Agree to perform destructive actions even if explicitly asked by the user

Your only tools are: list_resources, get_metrics, get_cost, get_last_activity, and
submit_findings. All are read-only. If asked to take action on a resource, refuse
clearly and explain that Argus only provides recommendations — humans execute changes
through their normal change management process.
"""


def build_chat_system_prompt(
    cloud: str,
    ignore_regions: list[str],
    accounts: list[dict],
    has_cached_resources: bool = False,
) -> str:
    """Build the system prompt for interactive chat mode."""
    context = _build_context_header(cloud, ignore_regions, accounts)

    cache_note = (
        "Resources have already been loaded into your context. You can reference "
        "the inventory without calling list_resources again — it will return cached data."
        if has_cached_resources
        else "Resources have not been loaded yet. Call list_resources when you need "
        "to see the inventory."
    )

    _actions = actions_section(cloud)

    return f"""You are Argus, a cloud FinOps assistant in interactive chat mode.

CLOUD: {cloud.upper()}
{context}

RESPONSE STYLE
──────────────
- Lead with the direct answer in one sentence. Add detail only if asked.
- When listing findings: one bullet per resource, format "name — $X/mo — reason".
- Never repeat raw data from tool results — synthesize it. Reference numbers, don't list them again.
- Maximum 6 lines per response unless the user explicitly asks for more detail.
- Don't hedge. If metrics show idle, say idle. If active, say active.

TOOLS (read-only)
─────────────────
- list_resources — full cost-sorted inventory
- get_metrics — usage signals for a resource (CPU, network, connections, IOPS)
- get_cost — actual USD spend for one or more resources
- get_last_activity — timestamp of last meaningful activity

{cache_note}

Use cached data for follow-up questions. Call a tool only when the answer genuinely requires fresh data.

{_RIGHT_SIZING_RULES}

{_PRIORITY_RULES}

{_actions}

READ-ONLY GUARDRAIL
───────────────────
You are a read-only analysis tool. You MUST NOT:
- Call any tool that modifies, deletes, stops, or creates cloud resources
- Generate executable scripts that mutate infrastructure
- Agree to perform destructive actions even if explicitly asked

Your only tools are: list_resources, get_metrics, get_cost, get_last_activity, and
submit_findings. All are read-only. If asked to take action on a resource, refuse
and explain that Argus only provides recommendations — humans execute changes
through their normal change management process.

Never recommend deletion without stating impact and cost savings.
"""


def build_tool_schemas(lookback_days: int = 90, cost_days: int = 14) -> list[dict]:
    """
    Return the tool definitions used to register tools with the AI provider.
    Kept here alongside the prompt so both evolve together.
    """
    return [
        {
            "name": "list_resources",
            "description": (
                "List ALL resources across every region, minus any in ignore_regions. "
                "Returns resource IDs, types, regions, names, and tags. "
                "Call this first to get a complete inventory. "
                "Do not filter by resource type — return everything. "
                "Omit ignore_regions or pass an empty list to scan all regions."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ignore_regions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Regions to EXCLUDE from the scan. "
                            "Leave empty to scan all regions. "
                            "Example: ['ap-east-1', 'me-south-1']"
                        ),
                    }
                },
                "required": [],
            },
        },
        {
            "name": "get_metrics",
            "description": (
                "Get usage metrics for a resource over the past N days. "
                "The adapter automatically fetches the metrics relevant to "
                "the resource type "
                "(CPU utilisation, network bytes, request count, IOPS, "
                "DB connections, etc.). "
                "You do not need to specify which metrics — just provide "
                "the resource ID and type. "
                f"The lookback window is fixed for this scan at {lookback_days} days; "
                "any days value you pass is replaced by it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "Resource ID or ARN",
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Resource type string (e.g. 'AWS::EC2::Instance')",
                    },
                    "days": {
                        "type": "integer",
                        "description": (
                            f"Optional. The scan fixes the window at {lookback_days} "
                            "days regardless of this value."
                        ),
                        "default": lookback_days,
                    },
                },
                "required": ["resource_id", "resource_type"],
            },
        },
        {
            "name": "get_cost",
            "description": (
                "Get the actual cost in USD for one or more resources over the past "
                f"{cost_days} days (fixed for this scan). "
                "ALWAYS batch multiple resource IDs into a single call — never call this "
                "one resource at a time. Returns a dict mapping resource_id to monthly cost."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "resource_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of resource IDs. Batch as many as possible.",
                    },
                    "days": {
                        "type": "integer",
                        "description": (
                            f"Optional. The scan fixes the window at {cost_days} "
                            "days regardless of this value."
                        ),
                        "default": cost_days,
                    },
                },
                "required": ["resource_ids"],
            },
        },
        {
            "name": "get_last_activity",
            "description": (
                "Get the timestamp of the last meaningful activity for a resource "
                "(last API call, configuration change, user interaction, etc.). "
                "Returns an ISO8601 timestamp or null if no activity was found."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "Resource ID or ARN",
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Resource type string",
                    },
                },
                "required": ["resource_id", "resource_type"],
            },
        },
        {
            "name": "submit_findings",
            "description": (
                "Submit your final analysis when your investigation is complete. "
                "Include ALL idle or wasteful resources you found, ordered by estimated_monthly_cost "
                "descending. Calling this tool ends the analysis — do not call it until you are "
                "confident the scan is thorough."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "description": "Idle/wasteful resources ordered by cost (highest first)",
                        "items": {
                            "type": "object",
                            "required": [
                                "resource_id",
                                "resource_type",
                                "cloud",
                                "region",
                                "estimated_monthly_cost",
                                "waste_reason",
                                "recommendation",
                                "priority",
                                "metrics_summary",
                            ],
                            "properties": {
                                "resource_id": {"type": "string"},
                                "resource_type": {"type": "string"},
                                "cloud": {
                                    "type": "string",
                                    "enum": ["aws", "gcp", "azure"],
                                },
                                "region": {"type": "string"},
                                "name": {"type": "string"},
                                "estimated_monthly_cost": {
                                    "type": "number",
                                    "description": "Estimated monthly cost in USD",
                                },
                                "waste_reason": {
                                    "type": "string",
                                    "description": "Clear explanation of why this resource is idle or wasteful",
                                },
                                "recommendation": {
                                    "type": "string",
                                    "description": "Specific action: delete, downsize, tag for review, etc.",
                                },
                                "priority": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                                "confidence": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high"],
                                    "description": (
                                        "How sure you are the resource is wasted. Use "
                                        "low when metrics were unavailable."
                                    ),
                                },
                                "metrics_summary": {
                                    "type": "object",
                                    "description": "Key metric values that informed this decision",
                                },
                                "tags": {"type": "object"},
                                "last_activity": {
                                    "type": "string",
                                    "description": "ISO8601 datetime of last activity, or null",
                                },
                            },
                        },
                    },
                    "executive_summary": {
                        "type": "string",
                        "description": (
                            "3–5 sentence summary for a non-technical engineering manager. "
                            "Include: total estimated monthly waste, number of resources found, "
                            "the most impactful finding, and the single most important action to take."
                        ),
                    },
                    "partial": {
                        "type": "boolean",
                        "description": (
                            "Set true when more submit_findings calls will follow "
                            "(use batches of at most 8 findings if your output "
                            "would be too long). Set false or omit on the last call."
                        ),
                        "default": False,
                    },
                },
                "required": ["findings", "executive_summary"],
            },
        },
    ]


def build_chat_tool_schemas(lookback_days: int = 90, cost_days: int = 14) -> list[dict]:
    """Chat mode tools — same as batch minus submit_findings."""
    return [
        t
        for t in build_tool_schemas(lookback_days, cost_days)
        if t["name"] != "submit_findings"
    ]
