---
title: Roadmap
description: What's coming next in Argus
---

# Roadmap

v0.4.0 focused on making multi-cloud usage practical and adding interactive chat. Here's what's coming next. No dates are promised; items ship when they're ready and well-tested.

Have a feature request? [Open an issue](https://github.com/vamshisiddarth/argus/issues) — community input shapes what gets built next.

---

## Phase 1 — Next

### :material-database-outline: Resource Registry

A centralized, declarative registry for every resource type Argus knows about.

**The problem today:** resource type metadata — discovery queries, metric names, cost keys, last-activity log patterns — is scattered across adapter files. Adding a new resource type means touching 4–5 files across the codebase.

**What changes:**

- Each resource type declared once in a single dataclass with all metadata attached
- Adding a new type means adding one entry to one file
- Agent prompt, report generator, and chat mode all read from the registry automatically
- Makes community contributions (new resource types, new clouds) dramatically easier

---

### :material-wrench-outline: Remediation v1

Let Argus act on findings, not just report them — safely.

**What it covers:**

- Targeted actions per finding: stop idle instances, delete orphaned volumes, release unassociated IPs
- **Policy layer built in from day one** — production-tagged resources are never touched without an explicit override; configurable rules per resource type and environment
- **Approval-gated by default** — Argus proposes the action, waits for explicit confirmation before executing anything
- Slack-native approval flow: approve or reject directly from the finding digest
- Full audit log of every action taken

**What it does not do:** bulk operations, irreversible actions without confirmation, or anything outside the explicitly approved scope.

---

### :material-chart-timeline: Historical Tracking

Track findings over time to measure progress and surface accountability gaps.

**What changes:**

- Findings compared week-over-week; new, resolved, and recurring findings clearly distinguished
- Resources flagged repeatedly appear with a "flagged N times" badge
- Weekly digest includes "X findings resolved since last week, saving $Y/mo"
- Resolution tracking: when waste is eliminated, the date and estimated savings are recorded

---

## Phase 2 — Later

### :material-api: MCP Server

Expose Argus as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server so any AI assistant can call it as a tool — Claude Desktop, Cursor, or any MCP-compatible client. REST API exposed alongside for integration with PagerDuty, Jira, and custom dashboards.

---

### :material-account-arrow-right-outline: Owner Routing & Advanced Policies

Route findings to per-team Slack channels based on resource tags (`owner=platform`, `team=data-eng`). Configurable suppression rules, repeated-finding escalation, and budget-aware prioritization.

---

### :material-brain: Decision Engine Enhancements

Build on the policy layer introduced in Remediation v1 — confidence scoring, cross-account pattern detection, and automated triage for high-volume accounts.

---

!!! note "Suggesting features"
    If one of these matters more to you than another, say so in
    [GitHub Discussions](https://github.com/vamshisiddarth/argus/discussions) — it influences prioritization.
