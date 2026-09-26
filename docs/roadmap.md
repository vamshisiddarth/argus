---
title: Roadmap
description: Argus project status — what has shipped, known gaps, and what's next
---

# Roadmap

This page is the current status of Argus as of **v0.6.0**: what has shipped, what is known to be incomplete, and what is planned next. It is the single source of truth for project status; older planning documents have been retired. No dates are promised; items ship when they're ready and well-tested.

Have a feature request? [Open an issue](https://github.com/vamshisiddarth/argus/issues) — community input shapes what gets built next.

---

## :material-check-circle-outline: Shipped in v0.6.0

A safety release for the remediation path. **Contains a breaking change**; see the [changelog](https://github.com/vamshisiddarth/argus/blob/main/CHANGELOG.md).

- **Automatic tickets are opt-in.** Scheduled scans create Jira tickets only when `REMEDIATION_ENABLED=true` (default `false`). `argus policies apply --confirm` is unchanged.
- **Dry runs never touch Jira.** `DRY_RUN=true` / `argus scan --dry-run` previously still created real tickets when Jira was configured. Dry runs now only log what would be tracked.
- **One summary line per run.** `remediation_summary findings=… proposals=… tracked=… failed=… dry_run=…`, plus `error_type` on every failure so a Jira outage can be told apart from a bug.
- **One policy-folder setting.** The CLI and scheduled scans now both read `ARGUS_POLICY_DIR` (the older `ARGUS_POLICIES_DIR` still works).
- **Policy excludes work as documented.** Matching any `exclude` tag entry now skips the resource, so the bundled `environment: prod` and `argus-exempt: "true"` excludes each work on their own (before, a resource needed both tags to be skipped).
- **`accounts` scope filters work.** Findings now record the account/project/subscription they came from.
- **No repeat Jira comments.** An unchanged finding no longer adds a comment to its ticket on every re-scan.

---

## :material-check-circle-outline: Shipped in v0.5.0

### Resource Registry
Each of the 114 supported resource types is now declared once — discovery query, metric names, cost key, display name — and the agent prompt, report, and chat mode all read from it automatically. Adding a new type is a one-file change.

### Remediation v1 — Policy-driven Jira tickets
Argus finds waste and now also creates Jira tickets for matched findings automatically.

- Write a YAML policy file per resource type (see `config/policies.example/`)
- Argus evaluates findings against your policies after every scan (opt-in since v0.6.0 via `REMEDIATION_ENABLED=true`)
- A Jira ticket is opened for each match — deduplication prevents re-creating tickets for the same resource on the next scan
- If the AI's analysis changes (cost drifts, priority changes), Argus adds a comment to the existing ticket rather than opening a duplicate
- Ticket URLs are posted to Slack alongside the waste digest so nothing gets lost
- Full audit log (`audit.jsonl`) of every ticket created

**What Remediation v1 does not do:** auto-execute cloud commands. Argus proposes; your team acts. Auto-remediation (approval gate → executor service) is Remediation v2 — see below.

---

## :material-alert-circle-outline: Known gaps

Small, known issues in what has shipped. Not scheduled; contributions welcome.

- **Slack ticket count wording.** The digest says "N remediation ticket(s) created", but N includes existing tickets that were only updated or left unchanged.
- **No decision tracing.** There is no trace of the agent's tool calls and reasoning per finding (Langfuse-style). Debugging a wrong "idle" call relies on logs and the report's AI reasoning text.
- **Logs, not metrics.** Remediation outcomes are structured log lines only; there are no counters exported to CloudWatch / Cloud Monitoring / Azure Monitor.
- **`SLACK_WEBHOOK_URL` is always required.** Startup validation insists on it (unless `DRY_RUN=true`) even when `NOTIFICATION_PROVIDER` only lists `teams` or `webhook`.
- **`BEDROCK_MAX_TOKENS` is ignored.** The Bedrock provider always requests up to 4096 output tokens.
- **AWS template doesn't expose `RESOURCE_EXPLORER_REGION`.** Deployed Lambdas assume the aggregator index is in `us-east-1` unless you add the variable by hand.
- **GCP deploy script doesn't enable the Vertex AI API** even though Vertex AI is the default provider on Cloud Run.
- **Bundled policies aren't in the PyPI package.** `pip install` users don't get `config/policies/`; copy it from the repository (or write your own) and point `ARGUS_POLICY_DIR` at it.
- **Docs deploys can race.** The docs workflow has no `concurrency` group, so merges landing seconds apart start parallel `mike deploy --push` runs to `gh-pages` and all but the first fail. Re-running the latest failed run fixes the site; adding a concurrency group to `.github/workflows/docs.yml` would prevent it.

---

## :material-wrench-outline: Remediation v2 — Auto-execution

**Status: planned, not started.** Everything below this line is future work; none of it is in v0.6.0.

**The problem:** Remediation v1 (shipped in v0.5.0, made opt-in in v0.6.0) creates tickets. Acting on them still requires manual work.

**What changes:**

- Jira ticket approval triggers a webhook to a dedicated executor service
- Executor carries out the action (stop, resize, delete) using a write-scoped IAM role
- Argus itself stays strictly read-only — the executor is a separate, scoped component
- Full rollback support for reversible actions (stop → can restart, snapshot → preserved)
- Guardrails: dry-run mode, per-action confirmation window, automatic revert on anomaly

**Why it's not in v1:** write-scoped execution requires a separate trust boundary and a much higher bar for testing. Building it half-finished would be worse than not building it.

---

## :material-chart-timeline: Historical Tracking

**Already shipped:** each report compares against the previous scan — findings are marked `new` or `recurring`, and `scan_diff` counts new, recurring, and resolved findings.

**The problem:** that comparison only looks one scan back and isn't surfaced in the digest, so it's hard to see whether waste is trending down or the same resources keep coming back.

**What changes:**

- Resources flagged repeatedly surface with a "flagged N times" badge
- Weekly digest includes "X findings resolved since last week, saving $Y/mo"

---

## :material-account-arrow-right-outline: Owner Routing

**The problem:** a single Slack channel becomes noise when findings span multiple teams.

**What changes:**

- Route findings to per-team channels based on resource tags (`owner=platform`, `team=data-eng`)
- Configurable suppression rules and repeated-finding escalation
- Requires consistent tagging hygiene across the account to be effective

---

## :material-api: MCP Server

**The problem:** accessing Argus requires the CLI or a Slack digest — not useful inside AI-first workflows.

**What changes:**

- Expose Argus as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server
- Claude Desktop, Cursor, or any MCP-compatible client can query your cloud costs live
- REST API exposed alongside for integration with PagerDuty, Jira, and custom dashboards

---

!!! note "Suggesting features"
    If one of these matters more to you than another, say so in
    [GitHub Discussions](https://github.com/vamshisiddarth/argus/discussions) — it influences prioritization.
