# Policies

Policies are YAML files that tell Argus which findings deserve a Jira ticket and what action to propose. Argus ships 13 bundled policies; you can add your own in `config/policies/`.

## Policy YAML format

```yaml
version: "1"

policy_id: aws-rds-resize-high-cost-idle   # (1) unique across all files
name: Resize idle high-cost RDS instances
resource_type: AWS::RDS::DBInstance        # (2) or "*" for all types
action: resize                             # (3) must be in registry spec.actions
weight: 20                                 # (4) higher = evaluated first

conditions:                                # ALL must pass
  ai_priority: [high, medium]              # Tier 1 — AI-assigned priority
  min_estimated_monthly_cost_usd: 100      # Tier 1 — cost floor
  idle_days_min: 14                        # Tier 1 — days since last activity
  metrics:                                 # Tier 2 — metric thresholds (registry-known types)
    - metric: CPUUtilization_avg
      operator: lt
      threshold: 5.0

include:                                   # scope filter — omit to match all
  cloud_platforms: [aws]
  regions: [us-east-1, us-west-2]
  tags:
    - team: [platform, infra]

exclude:                                   # exclusion filter — omit for none
  tags:
    - environment: [prod, production]
    - argus-exempt: ["true"]
```

1. `policy_id` must be unique across all files in the directory. Validation fails on duplicates.
2. `resource_type` must match the registry exactly (e.g. `AWS::RDS::DBInstance`). Use `*` to match any type.
3. `action` is validated against the registry for known resource types — an invalid action fails at load time.
4. `weight` controls evaluation order. The **highest-weight matching policy wins** for each resource — lower-weight policies are skipped.

## Condition tiers

### Tier 1 — universal

Applied to all resource types. All specified conditions must pass.

| Field | Type | Description |
|-------|------|-------------|
| `ai_priority` | list | AI-assigned priority: `high`, `medium`, `low` |
| `min_estimated_monthly_cost_usd` | float | Resource must cost at least this per month |
| `idle_days_min` | int | Days since last activity (requires `last_activity` data) |

### Tier 2 — metric thresholds

Only applied for registry-known resource types. Each entry must specify:

| Field | Values | Description |
|-------|--------|-------------|
| `metric` | string | Metric key in `metrics_summary` (see `argus policies docs <TYPE>`) |
| `operator` | `lt`, `gt`, `lte`, `gte`, `eq` | Comparison operator |
| `threshold` | float | Value to compare against |

All metric conditions must pass (AND logic). If a metric is not present in `metrics_summary`, that condition is skipped. If a metric value is not numeric, the condition fails.

!!! tip "Finding valid metric names"
    Run `argus policies docs AWS::RDS::DBInstance` to see all valid metrics and actions for a resource type.

## Rightsizing

For `resize` and `reduce_nodes` actions, Argus automatically computes a specific target recommendation from the observed CPU% in `metrics_summary`:

| Resource type | CPU% → recommendation |
|--------------|----------------------|
| `AWS::RDS::*` | < 5% → `db.t3.micro`, < 15% → `db.t3.small`, < 30% → `db.t3.medium` |
| `AWS::EC2::Instance` | < 3% → `t3.nano/micro`, < 10% → `t3.small`, < 25% → `t3.medium` |
| GKE / AKS clusters | < 15% CPU + node count → "reduce to N nodes (target 60% utilisation)" |

The recommendation appears inline in the `plan` table and in the Jira ticket Recommendation section. It is advisory — the human decides.

## Scope filters

Both `include` and `exclude` support the same fields:

| Field | Type | Description |
|-------|------|-------------|
| `cloud_platforms` | list | `aws`, `gcp`, `azure` |
| `accounts` | list | Account IDs / project IDs / subscription IDs |
| `regions` | list | Region names (e.g. `us-east-1`, `europe-west1`) |
| `tags` | list of dicts | Each entry is `{key: [values]}` — resource must have ALL matching tags |

`exclude` takes precedence — a resource that matches both `include` and `exclude` is excluded.

!!! warning "Always exclude production"
    All bundled policies exclude `environment: [prod, production]` and `argus-exempt: ["true"]`. Follow the same pattern in your own policies.

## Bundled policies

| Policy ID | Cloud | Action | Cost floor | Idle days |
|-----------|-------|--------|-----------|-----------|
| `aws-ec2-stop-idle-14d` | AWS | stop | $20/mo | 14 |
| `aws-rds-resize-high-cost-idle` | AWS | resize | $100/mo | 14 |
| `aws-ebs-delete-unattached-30d` | AWS | delete | $5/mo | 30 |
| `aws-elb-delete-idle` | AWS | delete | $20/mo | — |
| `aws-elasticache-delete-idle-30d` | AWS | delete | $50/mo | 30 |
| `aws-lambda-delete-unused-30d` | AWS | delete | $0 | 30 |
| `aws-redshift-snapshot-delete-14d` | AWS | snapshot_delete | $100/mo | 14 |
| `gcp-compute-stop-idle-7d` | GCP | stop | $20/mo | 7 |
| `gcp-sql-stop-idle-14d` | GCP | stop | $20/mo | 14 |
| `gcp-gke-reduce-nodes-underutilised` | GCP | reduce_nodes | $200/mo | — |
| `azure-vm-stop-idle-14d` | Azure | stop | $20/mo | 14 |
| `azure-sql-resize-underutilised` | Azure | resize | $50/mo | — |
| `azure-aks-reduce-nodes-underutilised` | Azure | reduce_nodes | $150/mo | — |

## Writing your own policy

1. Copy a bundled policy as a starting point.
2. Set a unique `policy_id`.
3. Run `argus policies validate --dir config/policies` — fix any errors.
4. Run `argus policies plan --report <scan.json>` to see which findings it matches.
5. Add a test in `tests/core/remediation/` — see [CONTRIBUTING.md](../../CONTRIBUTING.md).

!!! note "Safety rules"
    - Never remove the `argus-exempt: ["true"]` exclude — it's the emergency off-switch for individual resources.
    - `weight` reflects your confidence in the policy, not the severity of the finding. A catch-all `*` policy should have a lower weight than a targeted one.
    - Prefer conservative cost floors — it's better to miss a cheap idle resource than to ticket a resource that's actually in use.
