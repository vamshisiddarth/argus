# CLI Reference — `argus policies`

All remediation commands are under the `argus policies` subcommand.

## `validate`

Check all policies in a directory for errors and warnings before running a plan.

```bash
argus policies validate --dir config/policies
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--dir` | `ARGUS_POLICY_DIR` or `./config/policies` | Directory containing `*.yaml` policy files |

**Exit codes**

| Code | Meaning |
|------|---------|
| 0 | All policies valid (warnings printed but not fatal) |
| 1 | One or more errors (files that fail to load, duplicate IDs, invalid actions, weight conflicts, etc.) |

**Example output**

```
  ✓ aws-ebs-delete-unattached.yaml  weight: 15    resource: AWS::EC2::Volume
  ✓ aws-ec2-stop-idle.yaml          weight: 10    resource: AWS::EC2::Instance
  ...
  ✓ gcp-sql-stop-idle.yaml          weight: 20    resource: sqladmin.googleapis.com/Instance

13 policies loaded — 0 error(s), 0 warning(s).
```

A file that fails to load is reported with the reason, e.g.
`✗ bad.yaml: invalid action 'fly'. Must be one of: [...]`. Warnings (such as a lower-weight
policy that is fully shadowed by a higher-weight one) are printed but don't fail validation.

---

## `plan`

Evaluate policies against a scan report and print the proposal table. **Dry run — no tickets created.**

```bash
argus policies plan --report local_reports/aws/2026/09/27/<scan-id>.json
argus policies plan --live --cloud aws      # run a fresh scan instead (incurs API/AI cost)
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--report` | — | Path to an existing scan report JSON (fast, no cloud calls) |
| `--live` | off | Run a live scan instead of reading `--report` |
| `--cloud` | — | `aws` \| `gcp` \| `azure` — required with `--live` |
| `--dir` | `ARGUS_POLICY_DIR` or `./config/policies` | Policy directory |

One of `--report` or `--live` is required.

**Example output**

```
┌─────────────────────────────────────────────────────────────────────┐
│             POLICY PLAN — scan.json — 2026-09-27                    │
│              3 finding(s) · 13 policies · 2 match(es)               │
└─────────────────────────────────────────────────────────────────────┘

  POLICY                 RESOURCE                COST/MO  ACTION
  ─────────────────────  ─────────────────────  ────────  ──────────────
  ● aws-ec2-stop-idle-14d  i-0abc123def                $28  stop
  ● aws-ebs-delete-unatta  vol-orphan-0def8             $8  snapshot_delete

  – aws-elasticache-delete-idle-30d  (no findings matched)
  ...

───────────────────────────────────────────────────────────────────────
  2 match(es)  ·  Potential savings: $36/mo

  Jira ticket preview (2 ticket(s) would be created):
  · [Argus] Stop i-0abc123def ($28/mo · high priority)
  · [Argus] Snapshot & delete vol-orphan-0def8 ($8/mo · medium priority)

  Next step: Run with --confirm to create Jira tickets.
```

For `resize` and `reduce_nodes` matches, a rightsizing hint such as
`↳ Recommend db.t3.small (observed CPU ~8.0%)` is shown under the row.

Priority dots: 🔴 high · 🟡 medium · ⚪ low

---

## `apply`

Same as `plan` but creates Jira tickets when `--confirm` is passed.

```bash
# Dry run (same as plan)
argus policies apply --report local_reports/scan.json

# Create tickets
argus policies apply --report local_reports/scan.json --confirm
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--report` | — | Path to an existing scan report JSON |
| `--live` / `--cloud` | off | Run a live scan instead (same as `plan`) |
| `--dir` | `ARGUS_POLICY_DIR` or `./config/policies` | Policy directory |
| `--confirm` | false | Create/update Jira tickets (requires Jira env vars) |

`apply --confirm` works regardless of `REMEDIATION_ENABLED`; that setting only controls
automatic tickets after scheduled scans.

**Required env vars** (when `--confirm` is set)

```bash
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_USER_EMAIL=you@yourorg.com
JIRA_API_TOKEN=your-token
ARGUS_INTEGRATIONS_CONFIG=config/integrations.yaml
```

**Example output** (with `--confirm`)

```
  ✓ i-0abc123def  →  https://yourorg.atlassian.net/browse/COST-42
  ✓ vol-orphan-0def8  →  https://yourorg.atlassian.net/browse/COST-38

  2 ticket(s) created/updated, 0 failed.
```

A resource that already has an open ticket shows that ticket's URL; no duplicate is created.

---

## `stats`

Read the audit log and print per-policy acceptance rate stats.

```bash
argus policies stats
argus policies stats --days 90
argus policies stats --audit-log /var/log/argus/audit.jsonl
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--audit-log` | `ARGUS_AUDIT_LOG` env var or `./local_reports/audit.jsonl` | Path to audit log |
| `--days` | 30 | Only count proposals from the last N days |

**Example output**

```
Policy Proposal Stats — last 30 days

  POLICY                           PROPOSALS  JIRA NEW  JIRA UPDATE  CLOUDS
  ──────────────────────────────────────────────────────────────────────────
  aws-rds-resize-high-cost-idle            8         3            5  aws
  aws-ec2-stop-idle-14d                   12         7            5  aws
  azure-vm-stop-idle-14d                   4         2            2  azure
  ──────────────────────────────────────────────────────────────────────────
  TOTAL                                   24        12
```

---

## `docs`

Show registry metadata, valid metrics, and valid actions for a resource type.

```bash
# List all known resource types
argus policies docs

# Show details for a specific type
argus policies docs AWS::RDS::DBInstance
argus policies docs --cloud gcp
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `resource_type` | (positional, optional) | e.g. `AWS::RDS::DBInstance` — omit to list all |
| `--cloud` | none | Filter by cloud when listing all types |

**Example output**

```
  ┌──────────────────────────────────────────────────────────────┐
  │  AWS::RDS::DBInstance                                        │
  │  RDS Instance                                                │
  │  cloud: aws                                                  │
  └──────────────────────────────────────────────────────────────┘

  ▸ Tier 1 Conditions  (universal — all resource types)
    min_estimated_monthly_cost_usd          float     Min cost (USD/mo) to trigger
    ai_priority                             list      [high] / [medium] / [low]
    idle_days_min                           int       Days since last activity

  ▸ Tier 2 Conditions  (metric-based — this type only)
    CPUUtilization                          float     lt / gt / lte / gte / eq
    DatabaseConnections                     float     lt / gt / lte / gte / eq
    NetworkReceiveThroughput                float     lt / gt / lte / gte / eq

  ▸ Valid actions:  [delete]  [resize]  [stop]  [snapshot_delete]
```
