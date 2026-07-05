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
| `--dir` | `config/policies` | Directory containing `*.yaml` policy files |

**Exit codes**

| Code | Meaning |
|------|---------|
| 0 | All policies valid (warnings printed but not fatal) |
| 1 | One or more errors (duplicate IDs, invalid actions, negative values, etc.) |

**Example output**

```
✔  13 policies loaded, 0 errors, 2 warnings

  ⚠  aws-ec2-stop-idle-14d  weight=30 shadows  aws-ec2-stop-idle-catch-all  weight=10
     Both match AWS::EC2::Instance — lower-weight policy will never fire
```

---

## `plan`

Evaluate policies against a scan report and print the proposal table. **Dry run — no tickets created.**

```bash
argus policies plan --report local_reports/scan.json
```

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--report` | required | Path to scan report JSON |
| `--dir` | `config/policies` | Policy directory |

**Example output**

```
  POLICY                           RESOURCE               COST/MO  ACTION
  ─────────────────────────────────────────────────────────────────────────
  ● aws-rds-resize-high-cost-idle  db-analytics-01         $1,240  resize
    ↳ Recommend db.t3.small (observed CPU ~6.2%)
  ● aws-ec2-stop-idle-14d          i-0abc123def               $28  stop
  ● aws-ebs-delete-unattached-30d  vol-orphan-0def8            $8  delete
  ─────────────────────────────────────────────────────────────────────────
  Estimated savings: $1,276/mo across 3 proposals

  Next step: Run with --confirm to create Jira tickets.
```

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
| `--report` | required | Path to scan report JSON |
| `--dir` | `config/policies` | Policy directory |
| `--confirm` | false | Create/update Jira tickets (requires Jira env vars) |

**Required env vars** (when `--confirm` is set)

```bash
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_USER_EMAIL=you@yourorg.com
JIRA_API_TOKEN=your-token
ARGUS_INTEGRATIONS_CONFIG=config/integrations.yaml
```

**Example output** (with `--confirm`)

```
  Creating Jira tickets…

  ✔  COST-42  db-analytics-01  (new)
  ✔  COST-43  i-0abc123def     (new)
  –  COST-38  vol-orphan-0def8 (unchanged — skipped)
```

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
AWS::RDS::DBInstance
  Display name : RDS DB Instance
  Cloud        : aws
  Actions      : stop, resize, snapshot_delete
  Metrics      : CPUUtilization_avg, FreeStorageSpace_avg, DatabaseConnections_avg,
                 ReadIOPS_avg, WriteIOPS_avg, FreeableMemory_avg
```
