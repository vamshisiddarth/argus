# Remediation

Argus is **strictly read-only** — it never modifies a resource. The remediation system turns AI findings into prioritised Jira tickets that a human reviews and executes.

## How it fits together

```
argus scan   →   scan_report.json
                       │
                       ▼
argus policies plan    →   proposal table (dry run — no tickets created)
                       │
                       ▼  (add --confirm)
argus policies apply   →   Jira tickets + audit log entry per proposal
                       │
                       ▼  (ongoing)
argus policies stats   →   acceptance rate per policy from audit log
```

## Key properties

| Property | Detail |
|----------|--------|
| **Human gate** | Runbooks are printed in Jira tickets — Argus never executes them |
| **Idempotent** | Re-running `apply` on the same findings updates existing tickets, not new ones |
| **Audit trail** | Every create/update event appended to `local_reports/audit.jsonl` — never overwritten |
| **Rightsizing** | `resize` and `reduce_nodes` proposals include a specific target tier or node count |
| **Policy count** | 13 bundled policies across AWS, GCP, and Azure |

## Pages in this section

- [**Policies**](policies.md) — YAML format, bundled policies, writing your own
- [**Jira Integration**](jira.md) — setup, ticket lifecycle, ADF description, dedup
- [**CLI Reference**](cli.md) — `validate`, `plan`, `apply`, `stats`, `docs` subcommands
