---
title: Roadmap
description: What's coming next in Argus
---

# Roadmap

v0.4.1 focused on making multi-cloud usage practical and adding interactive chat. Here's what's coming next. No dates are promised; items ship when they're ready and well-tested.

Have a feature request? [Open an issue](https://github.com/vamshisiddarth/argus/issues) — community input shapes what gets built next.

---

## :material-database-outline: Resource Registry

**The problem:** resource type metadata — discovery queries, metric names, cost keys, last-activity log patterns — is scattered across adapter files. Adding a new resource type means touching 4–5 files.

**What changes:**

- Each resource type declared once in a single dataclass with all metadata attached
- Adding a new type means adding one entry to one file
- Agent prompt, report generator, and chat mode all read from the registry automatically

---

## :material-wrench-outline: Remediation v1

**The problem:** Argus finds waste and tells you what to do. Acting on it still requires manual work.

**What changes:**

- Targeted actions per finding: stop idle instances, delete orphaned volumes, release unassociated IPs
- **Safety is the foundation** — policy layer built in from day one; production-tagged resources are never touched without an explicit override; rules are configurable per resource type and environment
- **Approval-gated always** — Argus proposes, waits for your confirmation, then acts
- Slack-native approval flow: approve or reject directly from the finding digest
- Full audit log of every action taken

**What it does not do:** bulk operations, irreversible actions without confirmation, or anything outside explicitly approved scope.

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
