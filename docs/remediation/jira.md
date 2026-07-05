# Jira Integration

Argus creates Jira tickets for approved proposals. Each ticket contains the AI reasoning, key metrics, a copy-paste runbook, and a rightsizing recommendation (for resize/reduce_nodes actions).

## Setup

### 1 — Jira API token

Generate an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) and set these env vars:

```bash
export JIRA_BASE_URL=https://yourorg.atlassian.net
export JIRA_USER_EMAIL=you@yourorg.com
export JIRA_API_TOKEN=your-token-here
```

### 2 — Integrations config

Create `config/integrations.yaml` (gitignored — never commit this):

```yaml
jira:
  project_key: COST          # Jira project where tickets are created
  issue_type: Task           # or Story, Bug, etc.
  default_assignee: null     # optional: Jira account ID
  labels:
    - argus
    - cloud-cost
```

Set the path via `ARGUS_INTEGRATIONS_CONFIG` if you store it elsewhere:

```bash
export ARGUS_INTEGRATIONS_CONFIG=/path/to/config/integrations.yaml
```

## Ticket lifecycle

### Create

On first `apply --confirm` for a finding, Argus:

1. Searches for an existing open ticket with label `argus:<resource_id>:<policy_id>`
2. If none found — creates a new ticket with full ADF description
3. If found — updates the description (if the snapshot fingerprint changed) and adds a diff-comment

This makes `apply --confirm` **idempotent** — re-running after a re-scan either does nothing (finding unchanged) or updates the existing ticket (finding changed), never creates duplicates.

### Update on re-scan

If the same resource appears in a later scan with different metrics or cost:

- Argus detects the change via the **snapshot fingerprint** embedded in the ticket description
- It updates the description with new data
- It adds a comment: "Argus re-scan detected a change — description updated"

### Close

Argus does not auto-close tickets. When a human resolves a ticket in Jira, Argus will stop matching it on future scans (JQL filter: `statusCategory != Done`).

## Ticket structure (ADF)

Each ticket description has these sections:

| Section | Content |
|---------|---------|
| **Finding** | Resource ID, type, cloud, region, estimated monthly cost, AI priority, last activity |
| **Key Metrics** | Table of `metrics_summary` values (omitted if empty) |
| **Why Argus Flagged This** | AI-written `waste_reason` |
| **Recommendation** | AI-written `recommendation` + rightsizing hint (if applicable) |
| **Runbook** | Copy-paste CLI commands in a code block + "Human approval required" warning |
| **Policy** | `policy_id`, weight, source file |
| **Full Report** | Link to scan report (if `report_url` is set) |

## Audit log

Every `apply --confirm` appends a line to `local_reports/audit.jsonl`:

```json
{"ts":"2026-07-05T10:23:45+00:00","proposal_id":"uuid4","resource_id":"i-0abc","resource_type":"AWS::EC2::Instance","cloud":"aws","region":"us-east-1","policy_id":"aws-ec2-stop-idle-14d","action":"stop","estimated_monthly_cost_usd":28.40,"ai_priority":"high","jira_key":"COST-42","jira_url":"https://yourorg.atlassian.net/browse/COST-42"}
```

The file is append-only — multiple entries for the same `proposal_id` represent re-scans. Use `argus policies stats` to aggregate it.

Override the path with `ARGUS_AUDIT_LOG`:

```bash
export ARGUS_AUDIT_LOG=/var/log/argus/audit.jsonl
```

## Labels

Every Argus ticket gets these labels automatically:

| Label | Purpose |
|-------|---------|
| `argus` | Marks all Argus-created tickets |
| `argus:<resource_id>:<policy_id>` | Dedup key — one open ticket per resource per policy |
| `argus-priority-<high\|medium\|low>` | AI-assigned priority |
| `argus-action-<action>` | Proposed action (stop, resize, delete, etc.) |
| Any labels from `integrations.yaml` | Your custom labels |

!!! warning "Do not remove the dedup label"
    Removing `argus:<resource_id>:<policy_id>` from a ticket will cause Argus to create a duplicate on the next scan.
