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

**What it means today:** resource type metadata (discovery queries, metric names, cost keys, last-activity log patterns) is scattered across adapter files. Adding a new resource type means touching 4–5 files across the codebase.

**What the registry changes:**

- Each resource type is declared once — a single dataclass with all its metadata attached
- Adding a new type means adding one entry to one file
- The agent prompt, report generator, and chat mode all read from the registry automatically
- Makes community contributions (new resource types, new clouds) dramatically easier

**Who benefits:** contributors adding new resource types, and users who want Argus to cover more of their infrastructure.

---

## :material-wrench-outline: Remediation v1

Let Argus act on findings, not just report them.

**What it covers:**

- Safe, targeted actions per finding: delete orphaned resources, stop idle instances, release unassociated IPs
- **Approval-gated by default** — Argus proposes the action and waits for explicit confirmation before touching anything
- Dry-run mode: show exactly what would be deleted/changed without executing
- Full audit log of every action taken
- Slack-native approval flow: approve or reject directly from the finding digest

**What it does not do:** bulk deletions, anything irreversible without confirmation, or actions on production-tagged resources without an override flag.

**Who benefits:** teams who want to close the loop — find waste and eliminate it — without writing custom automation.

---

## :material-api: MCP Server

Expose Argus as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server so any AI assistant can call it as a tool.

**What it means:**

- Claude Desktop, Cursor, or any MCP-compatible client can call Argus directly
- Ask your AI assistant "what's wasting money in my AWS account?" and it queries Argus live
- No separate CLI or Slack setup needed — Argus becomes a tool your AI already has
- Works with all three clouds from a single MCP endpoint

**Who benefits:** users who live in AI-first workflows and want cloud cost intelligence inline with their existing assistant.

---

!!! note "Suggesting features"
    The order and scope of these items can change based on community feedback.
    If one of these matters more to you than another, say so in the
    [GitHub Discussions](https://github.com/vamshisiddarth/argus/discussions) — it influences prioritization.
