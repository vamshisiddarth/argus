---
title: Roadmap
description: What's coming next in Argus
---

# Roadmap

v0.5.0 ships policy-driven remediation and Jira integration. Here's what's coming next. No dates are promised; items ship when they're ready and well-tested.

Have a feature request? [Open an issue](https://github.com/vamshisiddarth/argus/issues) — community input shapes what gets built next.

---

## :material-check-circle-outline: Shipped in v0.5.0

### Resource Registry
Each of the 114 supported resource types is now declared once — discovery query, metric names, cost key, display name — and the agent prompt, report, and chat mode all read from it automatically. Adding a new type is a one-file change.

### Remediation v1 — Policy-driven Jira tickets
Argus finds waste and now also creates Jira tickets for matched findings automatically.

- Write a YAML policy file per resource type (see `config/policies.example/`)
- Argus evaluates findings against your policies after every scan
- A Jira ticket is opened for each match — deduplication prevents re-creating tickets for the same resource on the next scan
- If the AI's analysis changes (cost drifts, priority changes), Argus adds a comment to the existing ticket rather than opening a duplicate
- Ticket URLs are posted to Slack alongside the waste digest so nothing gets lost
- Full audit log (`audit.jsonl`) of every ticket created

**What Remediation v1 does not do:** auto-execute cloud commands. Argus proposes; your team acts. Auto-remediation (approval gate → executor service) is Remediation v2 — see below.

---

## :material-wrench-outline: Remediation v2 — Auto-execution

**The problem:** Remediation v1 creates tickets. Acting on them still requires manual work.

**What changes:**

- Jira ticket approval triggers a webhook to a dedicated executor service
- Executor carries out the action (stop, resize, delete) using a write-scoped IAM role
- Argus itself stays strictly read-only — the executor is a separate, scoped component
- Full rollback support for reversible actions (stop → can restart, snapshot → preserved)
- Guardrails: dry-run mode, per-action confirmation window, automatic revert on anomaly

**Why it's not in v1:** write-scoped execution requires a separate trust boundary and a much higher bar for testing. Building it half-finished would be worse than not building it.

---

## :material-chart-timeline: Historical Tracking

**The problem:** each scan is a snapshot. There's no way to tell if things are getting better or the same waste keeps coming back.

**What changes:**

- Findings compared week-over-week: new, resolved, and recurring clearly distinguished
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
