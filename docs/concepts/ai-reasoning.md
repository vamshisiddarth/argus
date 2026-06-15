# AI Reasoning

## Why AI instead of thresholds?

Traditional cost tools use hardcoded rules:

```python
# The old way — fragile, needs constant maintenance
if resource_type == "EC2" and cpu_avg < 5.0:
    flag_idle()
elif resource_type == "RDS" and connections_avg < 1.0:
    flag_idle()
elif resource_type == "NatGateway" and bytes_out == 0:
    flag_idle()
# ... 50 more elif blocks ...
```

This breaks immediately when:
- A resource has unusual usage patterns
- A new resource type is added
- Context matters (a dev database with zero connections on weekends isn't idle)

Argus takes a different approach: **give the AI the raw signal data and let it reason**.

## What Claude receives

For each candidate resource, the AI has access to:

- **Cost** — monthly USD from Cost Explorer / BigQuery
- **Metrics** — 90-day averages: CPU, network bytes, request count, IOPS, connections, etc.
- **Instance size** — current instance type/class injected alongside metrics (e.g. `instance_type: db.r5.4xlarge`, `memory_mb: 3072`)
- **Last activity** — timestamp of the last meaningful CloudTrail / Audit Log event
- **Tags** — owner, environment, team, purpose
- **Resource type and region** — context for what the resource is supposed to do

## How Claude decides

Claude applies qualitative reasoning that adapts to context:

!!! example "EC2 at 0.001% CPU"
    ```
    i-0abc is an EC2 t3.large instance with:
    - CPUUtilization avg: 0.0014% (90-day average)
    - NetworkIn avg: 0 bytes
    - NetworkOut avg: 0 bytes
    - Last CloudTrail event: null (no events in 90 days)
    - Tags: {} (no owner, no environment)
    - Cost: $28.40/month

    Assessment: This instance is effectively idle.
    A t3.large with 0.001% CPU and zero network traffic
    is not serving any workload. The absence of any tags
    suggests it may be a forgotten resource. No CloudTrail
    activity in 90 days confirms no recent human interaction.

    Priority: HIGH ($28.40/month, confirmed idle)
    Recommendation: Terminate. If data is needed, take an
    EBS snapshot first.
    ```

!!! example "RDS with zero connections — but recent activity"
    ```
    db-prod-replica has:
    - DatabaseConnections avg: 0.0
    - CPUUtilization avg: 0.3%
    - Last CloudTrail event: 2026-06-01T14:22:00Z (6 days ago)
    - Tags: {"Environment": "prod", "Owner": "platform-team"}
    - Cost: $45.00/month

    Assessment: This RDS instance shows zero connections but
    was modified 6 days ago by the platform team. It may be
    a standby replica, a recently migrated instance, or be
    used only during specific batch windows. The owner tag
    indicates active ownership.

    Priority: LOW (owned resource, recently touched)
    Recommendation: Tag for review — ask the platform team
    if this replica is still needed.
    ```

!!! example "RIGHT-SIZE: RDS over-provisioned"
    ```
    db-analytics-01 is an RDS db.r5.4xlarge with:
    - CPUUtilization avg: 4.2% (90-day average)
    - DatabaseConnections avg: 2.1
    - instance_type: db.r5.4xlarge
    - multi_az: true
    - engine: postgres 14.7
    - storage_gb: 500
    - Cost: $1,240/month

    Assessment: This database is severely over-provisioned.
    CPU at 4.2% and fewer than 3 concurrent connections over
    90 days on a db.r5.4xlarge (128 GB RAM, 16 vCPUs) indicates
    the workload could run comfortably on a db.r5.xlarge.
    Multi-AZ is also enabled, doubling the instance cost on a
    DB that is barely used.

    Priority: HIGH ($1,240/month, clear right-sizing opportunity)
    Recommendation: RIGHT-SIZE: db.r5.4xlarge → db.r5.xlarge
    (~$900/month savings). Also evaluate disabling Multi-AZ
    (~$620/month additional savings) if this is not a
    production-critical database.
    ```

## Priority rules

The system prompt defines the priority framework:

| Priority | Condition |
|----------|-----------|
| `HIGH` | Confirmed idle AND costs > $20/month |
| `MEDIUM` | Likely idle OR costs $5–$20/month |
| `LOW` | Possibly idle OR costs < $5/month |

Claude applies these rules but also exercises judgment — a $3/month resource that is
definitively orphaned (no tags, no activity, no owner) might still be flagged HIGH if
there are many of them in the account.

## System prompt

The system prompt is built once per scan in `core/agent/prompts.py`:

- Identifies the agent role and mission
- Lists accounts and regions being scanned
- Provides the investigation workflow (7 steps)
- Defines what to look for (6 categories of waste)
- Sets the priority rules
- Enforces efficiency rules (batch cost calls, don't over-investigate)

The prompt is **pinned in Anthropic's cache** — subsequent loop iterations reuse the cached
version, cutting the cost of the multi-turn conversation significantly.
