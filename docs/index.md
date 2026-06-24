---
title: Argus
description: AI-powered cloud cost optimization agent for AWS, GCP, and Azure
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

<div class="hero-badge"><span class="hero-badge-version">v0.4.0</span> · Open Source · MIT License</div>

# Stop Wasting Money on Idle Cloud Resources

AI finds what's wasting money across AWS, GCP, and Azure — idle, oversized, orphaned.
Ranked findings with exact actions, straight to Slack. Or ask questions live.

<div class="hero-buttons" markdown>
[Get Started](getting-started/index.md){ .md-button .md-button--primary }
[:material-github: View on GitHub](https://github.com/vamshisiddarth/argus){ .md-button }
</div>

<div class="cloud-badges">
<span class="cloud-badge cloud-badge--aws"><span class="cb-icon">AWS</span><span class="cb-label">Amazon Web Services</span></span>
<span class="cloud-badge cloud-badge--gcp"><span class="cb-icon">GCP</span><span class="cb-label">Google Cloud</span></span>
<span class="cloud-badge cloud-badge--azure"><span class="cb-icon">Azure</span><span class="cb-label">Microsoft Azure</span></span>
</div>

<div class="hero-stats">
  <div class="hero-stat"><strong>3</strong><span>clouds</span></div>
  <div class="hero-stat"><strong>43+</strong><span>resource types</span></div>
  <div class="hero-stat"><strong>528</strong><span>tests</span></div>
  <div class="hero-stat"><strong>~$0.25</strong><span>per scan</span></div>
</div>

</div>

---

## :material-magnify: What Argus finds

<div class="feature-grid" markdown>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-stop-circle-outline:</div>

**Stopped instances still charging**

EC2, GCE, and Azure VMs that are stopped but still paying for reserved storage and EIPs.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-database-remove:</div>

**Orphaned volumes and disks**

EBS volumes, GCP Persistent Disks, and Azure Managed Disks with zero I/O for weeks.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-lan-disconnect:</div>

**Idle load balancers and NAT gateways**

Resources processing zero bytes per day but billed by the hour.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-arrow-collapse-down:</div>

**Right-sizing opportunities**

RDS `db.r5.4xlarge` at 4% CPU? EC2 `m5.4xlarge` with zero traffic? Argus names the
current instance type and recommends the exact smaller tier — not "consider downsizing."
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-server-minus:</div>

**Over-provisioned clusters and caches**

EKS, GKE, and AKS node groups, ElastiCache clusters, and Redshift nodes running at
single-digit utilization — with specific node count and instance type recommendations.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-tag-remove:</div>

**Untagged and unowned resources**

Resources with no owner tag that nobody knows about — prime deletion candidates.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-chat-question-outline:</div>

**Interactive chat mode**

Ask questions in plain English: *"Which RDS instances have been idle for 30+ days?"*
Argus investigates live and answers with costs and recommendations.
</div>

</div>

---

## :material-cog-play-outline: How it works

<div class="arch-wrap">
<svg viewBox="0 0 800 420" xmlns="http://www.w3.org/2000/svg" class="arch-svg">
<defs>
  <marker id="ar" viewBox="0 0 10 7" markerWidth="8" markerHeight="6" refX="9" refY="3.5" orient="auto"><path d="M0,0 L10,3.5 L0,7 z" class="ah"/></marker>
  <marker id="ar-u" viewBox="0 0 10 7" markerWidth="8" markerHeight="6" refX="9" refY="3.5" orient="auto"><path d="M0,0 L10,3.5 L0,7 z" class="ah-u"/></marker>
  <marker id="ar-o" viewBox="0 0 10 7" markerWidth="8" markerHeight="6" refX="9" refY="3.5" orient="auto"><path d="M0,0 L10,3.5 L0,7 z" class="ah-o"/></marker>
  <marker id="ar-r" viewBox="0 0 10 7" markerWidth="8" markerHeight="6" refX="9" refY="3.5" orient="auto"><path d="M0,0 L10,3.5 L0,7 z" class="ah-r"/></marker>
</defs>
<!-- Cloud Account -->
<rect x="10" y="152" width="110" height="52" rx="8" class="n-src"/>
<text x="65" y="174" text-anchor="middle" class="nt">Cloud</text>
<text x="65" y="191" text-anchor="middle" class="nt nt-b">Account</text>
<!-- list_resources -->
<rect x="148" y="152" width="132" height="52" rx="8" class="n-tool"/>
<text x="214" y="171" text-anchor="middle" class="nt nt-d" font-size="10">Asset Inventory</text>
<text x="214" y="189" text-anchor="middle" class="nt nt-b">list_resources</text>
<!-- Agent Loop — tall central box; outputs hang below, tools connect horizontally right -->
<rect x="316" y="90" width="148" height="210" rx="12" class="n-agent"/>
<text x="390" y="122" text-anchor="middle" class="nt nt-b" font-size="13">Agent Loop</text>
<text x="390" y="140" text-anchor="middle" class="nt nt-d">ReAct</text>
<line x1="330" y1="150" x2="450" y2="150" class="n-div"/>
<text x="390" y="167" text-anchor="middle" class="nt nt-d" font-size="10">think→act→observe</text>
<text x="390" y="183" text-anchor="middle" class="nt nt-d" font-size="10">no idle thresholds</text>
<text x="390" y="199" text-anchor="middle" class="nt nt-d" font-size="10">AWS · GCP · Azure</text>
<!-- get_metrics -->
<rect x="500" y="105" width="185" height="50" rx="8" class="n-tool"/>
<text x="592" y="124" text-anchor="middle" class="nt nt-d" font-size="10">CloudWatch · Monitoring</text>
<text x="592" y="143" text-anchor="middle" class="nt nt-b">get_metrics</text>
<!-- get_cost -->
<rect x="500" y="183" width="185" height="50" rx="8" class="n-tool"/>
<text x="592" y="202" text-anchor="middle" class="nt nt-d" font-size="10">Cost Explorer · BigQuery</text>
<text x="592" y="221" text-anchor="middle" class="nt nt-b">get_cost</text>
<!-- get_last_activity -->
<rect x="500" y="255" width="185" height="50" rx="8" class="n-tool"/>
<text x="592" y="274" text-anchor="middle" class="nt nt-d" font-size="10">CloudTrail · Audit Logs</text>
<text x="592" y="293" text-anchor="middle" class="nt nt-b">get_last_activity</text>
<!-- User question -->
<rect x="10" y="310" width="142" height="52" rx="26" class="n-user"/>
<text x="81" y="332" text-anchor="middle" class="nt">User</text>
<text x="81" y="350" text-anchor="middle" class="nt nt-b">question</text>
<!-- Slack Report — below agent, left side -->
<rect x="195" y="368" width="148" height="45" rx="8" class="n-out"/>
<text x="269" y="387" text-anchor="middle" class="nt nt-d" font-size="10">argus scan</text>
<text x="269" y="404" text-anchor="middle" class="nt nt-b">Slack Report</text>
<!-- Chat Answer — below agent, right side -->
<rect x="432" y="368" width="148" height="45" rx="8" class="n-out"/>
<text x="506" y="387" text-anchor="middle" class="nt nt-d" font-size="10">argus chat</text>
<text x="506" y="404" text-anchor="middle" class="nt nt-b">Chat Answer</text>
<!-- ── Edges ── -->
<!-- Cloud → list_resources -->
<line x1="120" y1="178" x2="146" y2="178" class="e" marker-end="url(#ar)"/>
<!-- list_resources → Agent (36 px gap, arrow clearly visible) -->
<line x1="276" y1="178" x2="314" y2="178" class="e" marker-end="url(#ar)"/>
<!-- User question → Agent (orthogonal: right → up → right into agent left side) -->
<path d="M 152,336 L 234,336 L 234,295 L 316,295" class="e e-u" marker-end="url(#ar-u)"/>
<!-- Agent ↔ get_metrics (horizontal pair, 36 px gap) -->
<line x1="464" y1="122" x2="498" y2="122" class="e" marker-end="url(#ar)"/>
<line x1="498" y1="136" x2="464" y2="136" class="e e-r" marker-end="url(#ar-r)"/>
<!-- Agent ↔ get_cost (horizontal pair) -->
<line x1="464" y1="200" x2="498" y2="200" class="e" marker-end="url(#ar)"/>
<line x1="498" y1="214" x2="464" y2="214" class="e e-r" marker-end="url(#ar-r)"/>
<!-- Agent ↔ get_last_activity (horizontal pair) -->
<line x1="464" y1="268" x2="498" y2="268" class="e" marker-end="url(#ar)"/>
<line x1="498" y1="282" x2="464" y2="282" class="e e-r" marker-end="url(#ar-r)"/>
<!-- Agent → Slack Report (orthogonal: down → left → down into Slack top) -->
<path d="M 355,300 L 355,348 L 269,348 L 269,368" class="e e-o" marker-end="url(#ar-o)"/>
<!-- Agent → Chat Answer (orthogonal: down → right → down into Chat top) -->
<path d="M 440,300 L 440,348 L 524,348 L 524,368" class="e e-o" marker-end="url(#ar-o)"/>
</svg>
</div>

Argus uses a **ReAct agent loop** — the AI decides what to investigate, calls the right
tools in the right order, and reasons about idleness qualitatively. No hardcoded thresholds.
No rules per resource type. The same brain works across all three clouds.

Prefer conversational exploration? `argus chat` runs the same agent loop interactively —
ask *"Which RDS instances have been idle for 30+ days?"* and get a live, grounded answer.

---

## :material-slack: Example Slack report

```text
Argus — AWS Waste Report (2026-06-24)

💸 $1,432.85/month estimated waste
📊 6 idle resources across 1 account

Six resources were identified as idle or over-provisioned. The RDS instance
accounts for 87% of waste and should be right-sized immediately.

─────────────────────────────────────
Top findings
🔴 `db-analytics-01`  · RDS      · $1,240.00/mo
🔴 `cache-prod-001`   · ElastiCache · $142.00/mo
🔴 `i-0abc123def`     · EC2      ·    $28.40/mo
🟡 `nat-0def456`      · NAT Gateway · $10.80/mo
🟡 `vol-orphan`       · EBS      ·     $8.00/mo
⚪ +1 more finding in the full report

[ 📄 Full report (HTML) ]  [ vamshisiddarth/argus ]
```

---

## :material-rocket-launch-outline: Quick start

=== "Local scan"

    ```bash
    pip install argus-cloud-optimizer

    cp .env.example .env
    # Set ANTHROPIC_API_KEY and DRY_RUN=true

    argus scan --cloud aws --dry-run   # full weekly scan
    argus chat --cloud aws             # interactive Q&A
    ```

=== "AWS Lambda"

    ```bash
    aws cloudformation deploy \
      --template-file deploy/aws/single-account/template.yaml \
      --stack-name Argus \
      --capabilities CAPABILITY_IAM \
      --parameter-overrides \
          SlackWebhookUrl=https://hooks.slack.com/services/... \
          PrimaryRegion=us-east-1
    ```

    Deploys a Lambda + EventBridge rule (weekly scan) + IAM role. See [AWS deployment guide](deployment/aws.md) for multi-account setup.

=== "GCP"

    ```bash
    export GOOGLE_CLOUD_PROJECT=my-project
    export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
    bash deploy/gcp/deploy.sh
    ```

=== "Azure"

    ```bash
    az deployment group create \
      --resource-group Argus-RG \
      --template-file deploy/azure/function-app.bicep \
      --parameters \
          subscriptionIds="sub-id-1,sub-id-2" \
          slackWebhookUrl="https://hooks.slack.com/services/..."
    ```

---

## :material-shield-check-outline: Design principles

| | Principle | What it means |
|--|-----------|---------------|
| :material-brain: | **Same brain, different hands** | `core/` is pure Python — zero cloud imports. Adapters are the only place SDKs live. |
| :material-robot-outline: | **AI drives the analysis** | No hardcoded idle thresholds. Claude reasons about each resource in context. |
| :material-lock-outline: | **Least privilege always** | Read-only IAM roles. No write permissions ever requested. |
| :material-lightning-bolt-outline: | **Batch everything** | One Cost Explorer call per scan. One Bedrock call per scan. Cost control by design. |
| :material-alert-circle-outline: | **Fail loudly** | Typed exceptions from adapters. No silent swallowing of errors. |

---

!!! tip "Total cost of a weekly scan"
    A full AWS scan across 100 resources costs roughly **$0.25–0.50** using the Anthropic API
    (direct key) or **~$0.10** via AWS Bedrock. A single right-sizing recommendation
    (e.g. `db.r5.4xlarge → db.r5.xlarge`) typically saves **100–1,000× the scan cost** per month.
