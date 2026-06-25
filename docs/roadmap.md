---
title: Roadmap
description: What's coming next in Argus
---

# Roadmap

Argus is actively developed. These are the next major capabilities planned — listed in priority order. No dates are promised; items ship when they're ready and well-tested.

Have a feature request? [Open an issue](https://github.com/vamshisiddarth/argus/issues) — community input shapes what gets built next.

---

## :material-database-outline: Resource Registry

A centralized, declarative registry for every resource type Argus knows about.

**The problem today:** resource type metadata — discovery queries, metric names, cost keys, last-activity log patterns — is scattered across adapter files. Adding a new resource type means touching 4–5 files across the codebase.

**What changes:**

- Each resource type declared once in a single dataclass with all metadata attached
- Adding a new type means adding one entry to one file
- Agent prompt, report generator, and chat mode all read from the registry automatically
- Makes community contributions (new resource types, new clouds) dramatically easier

**Who benefits:** contributors adding new resource types, and users who want Argus to cover more infrastructure.

---

## :material-brain: Decision Engine

The intelligence layer that decides what Argus should act on, how urgently, and what it should ignore.

**The problem today:** Argus surfaces all findings and leaves prioritization entirely to the reader. A stopped dev EC2 and an idle production RDS get equal weight. Teams with hundreds of findings have no way to focus attention automatically.

**What changes:**

- **Policy-aware prioritization** — respects context: production vs dev, cost threshold, owner team, resource age, tag policies
- **Confidence scoring** — distinguishes "definitely idle" from "possibly idle, needs review" and presents them differently
- **Suppression rules** — mark a finding as expected (`argus-ignore=true`) and it stays out of future reports
- **Repeated-finding escalation** — a resource flagged three weeks in a row with no action gets elevated priority automatically
- **Budget-aware alerting** — tie findings to actual budget targets; surface critical findings first when a team is trending over budget

**Why this is high ROI:** the Decision Engine is what transforms Argus from a reporting tool into an operational one. Every downstream feature (Remediation, Owner Routing) becomes significantly more valuable when backed by a decision layer that knows what's safe to touch and what isn't.

---

## :material-wrench-outline: Remediation v1

Let Argus act on findings, not just report them.

**What it covers:**

- Safe, targeted actions per finding: delete orphaned resources, stop idle instances, release unassociated IPs
- **Approval-gated by default** — Argus proposes the action, waits for explicit confirmation before touching anything
- Slack-native approval flow: approve or reject directly from the finding digest
- Dry-run mode: show exactly what would change without executing
- Full audit log of every action taken
- Scheduled remediation: "delete this at 3am Saturday" rather than immediate

**What it does not do:** bulk deletions, anything irreversible without confirmation, or actions on production-tagged resources without an explicit override.

**Who benefits:** teams who want to close the loop — find waste and eliminate it — without writing custom automation.

---

## :material-account-arrow-right-outline: Owner Routing

Route each finding to the team that owns the resource, not just a single Slack channel.

**The problem today:** all findings go to one webhook. A platform team finding and a data engineering finding land in the same channel. Nobody owns it, nothing gets acted on.

**What changes:**

- Route findings to per-team Slack channels or webhooks based on resource tags (`owner=platform`, `team=data-eng`)
- Configurable routing rules: by tag, by resource type, by account/project, or by priority level
- Fallback channel for untagged/unowned resources (a strong incentive to fix tagging hygiene)
- Each team sees only their findings — no noise from other teams

**Who benefits:** organizations with multiple teams sharing a single cloud account or organization.

---

## :material-chart-timeline: Historical Tracking

Track findings over time to measure progress and surface accountability gaps.

**What changes:**

- Each scan's findings are persisted (S3/GCS/Blob) and compared against the previous scan
- **Trend view:** resources that have been idle for 2+ weeks appear with a "flagged N times" badge
- **Resolution tracking:** when a finding disappears (resource deleted or right-sized), it's marked resolved with the date
- **Progress report:** weekly digest includes "X findings resolved since last week, saving $Y/mo"
- **Drift alerts:** a resource that was resolved and then re-appears gets flagged as a regression

**Who benefits:** engineering managers who want to show cost reduction progress over time, and teams where accountability matters.

---

## :material-api: MCP Server

Expose Argus as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server so any AI assistant can call it as a tool.

**What it means:**

- Claude Desktop, Cursor, or any MCP-compatible client can call Argus directly
- Ask your AI assistant "what's wasting money in my AWS account?" and it queries Argus live
- No separate CLI or Slack setup needed — Argus becomes a tool your AI already has
- Works with all three clouds from a single MCP endpoint
- REST API surface exposed alongside MCP, enabling integration with PagerDuty, Jira, custom dashboards

**Who benefits:** users who live in AI-first workflows and want cloud cost intelligence inline with their existing assistant.

---

!!! note "Suggesting features"
    The order and scope of these items can change based on community feedback.
    If one of these matters more to you than another, say so in
    [GitHub Discussions](https://github.com/vamshisiddarth/argus/discussions) — it influences prioritization.
