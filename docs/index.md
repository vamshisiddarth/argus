---
title: Argus
description: Argus — AI Cloud Detective for AWS, GCP, and Azure
hide:
  - navigation
  - toc
---

<div class="hero">
<div class="hero-inner">
<div class="hero-left" markdown>

<div class="hero-badge" markdown><span class="hero-badge-version">v0.5.0</span> · Open Source · MIT License</div>

<p class="hero-tagline">AI Cloud Detective</p>

<h1 class="hero-h1">Stop Wasting Money<br>on Idle Cloud Resources</h1>

<p class="hero-sub">Argus finds what's wasting money across AWS, GCP, and Azure — idle, oversized, orphaned. Ranked findings with exact actions, straight to Slack. Or ask questions live.</p>

<div class="hero-buttons">
<a href="getting-started/" class="md-button md-button--primary">Get Started</a>
<a href="https://github.com/vamshisiddarth/argus" class="md-button">
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:-3px;margin-right:6px"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>View on GitHub
</a>
</div>

<div class="cloud-badges">
<span class="cloud-badge cloud-badge--aws"><span class="cb-icon">AWS</span><span class="cb-label">Amazon Web Services</span></span>
<span class="cloud-badge cloud-badge--gcp"><span class="cb-icon">GCP</span><span class="cb-label">Google Cloud</span></span>
<span class="cloud-badge cloud-badge--azure"><span class="cb-icon">Azure</span><span class="cb-label">Microsoft Azure</span></span>
</div>

<div class="hero-stats">
  <div class="hero-stat"><strong data-count="3">3</strong><span>clouds</span></div>
  <div class="hero-stat"><strong data-count="43" data-suffix="+">43+</strong><span>resource types</span></div>
  <div class="hero-stat"><strong data-count="565">565</strong><span>tests</span></div>
  <div class="hero-stat"><strong data-count="0.25" data-prefix="~$">~$0.25</strong><span>per scan</span></div>
</div>

</div>
<div class="hero-right">
<div class="hero-terminal">
  <div class="ht-bar">
    <span class="ht-dot" style="background:#ff5f57"></span>
    <span class="ht-dot" style="background:#febc2e"></span>
    <span class="ht-dot" style="background:#28c840"></span>
    <span class="ht-bar-title">argus chat — AWS · us-east-1</span>
  </div>
  <div class="ht-body" id="ht-body"></div>
</div>
</div>
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

<div class="how-steps">
  <div class="how-step">
    <div class="how-num">1</div>
    <h3>Discover</h3>
    <p>One API call to the cloud's asset inventory returns every billable resource across all regions — sorted by cost descending so the most expensive candidates are investigated first.</p>
  </div>
  <div class="how-connector">→</div>
  <div class="how-step">
    <div class="how-num">2</div>
    <h3>Investigate</h3>
    <p>A ReAct agent loop reasons like a human analyst — pulling 90-day metrics, actual spend, and last-activity timestamps only for resources where it matters. No hardcoded thresholds.</p>
  </div>
  <div class="how-connector">→</div>
  <div class="how-step">
    <div class="how-num">3</div>
    <h3>Report</h3>
    <p>Prioritized findings land in Slack with exact dollar amounts and specific actions — delete, right-size, or tag for review. Or skip the batch scan and ask questions live with <code>argus chat</code>.</p>
  </div>
</div>

Argus uses a **ReAct agent loop** — the AI decides what to investigate, calls the right tools in the right order, and reasons about idleness qualitatively. No hardcoded thresholds. No rules per resource type. The same brain works across all three clouds.

---

## :material-slack: Example Slack report

<div class="slack-mock">
  <div class="slack-topbar">
    <span class="s-hash">#</span> cloud-costs
  </div>
  <div class="slack-body">
    <div class="slack-msg">
      <div class="s-avatar">A</div>
      <div style="flex:1;min-width:0">
        <div class="s-meta">
          <span class="s-name">Argus</span>
          <span class="s-badge">APP</span>
          <span class="s-time">Today at 7:00 AM</span>
        </div>
        <div class="s-text">☁️ <strong>AWS Waste Report</strong> — weekly scan complete</div>
        <div class="s-attach">
          <div class="s-attach-title">💸 $1,432/mo estimated waste · 6 resources</div>
          <div class="s-attach-sub">Six resources identified as idle or over-provisioned. The RDS instance accounts for 87% of waste and should be right-sized immediately.</div>
          <div class="s-findings">
            <div class="s-row"><span class="s-dot s-dot-h"></span><span class="s-res">db-analytics-01</span><span class="s-type">RDS db.r5.4xlarge</span><span class="s-cost">$1,240/mo</span></div>
            <div class="s-row"><span class="s-dot s-dot-h"></span><span class="s-res">cache-prod-001</span><span class="s-type">ElastiCache r6g.large</span><span class="s-cost">$142/mo</span></div>
            <div class="s-row"><span class="s-dot s-dot-h"></span><span class="s-res">i-0abc123def</span><span class="s-type">EC2 m5.2xlarge (stopped)</span><span class="s-cost">$28/mo</span></div>
            <div class="s-row"><span class="s-dot s-dot-m"></span><span class="s-res">nat-0def456</span><span class="s-type">NAT Gateway</span><span class="s-cost">$11/mo</span></div>
            <div class="s-row"><span class="s-dot s-dot-m"></span><span class="s-res">vol-orphan</span><span class="s-type">EBS Volume (unattached)</span><span class="s-cost">$8/mo</span></div>
            <div class="s-more">+1 more finding in the full report</div>
          </div>
          <div class="s-btns">
            <span class="s-btn s-btn-p">📄 Full report (HTML)</span>
            <span class="s-btn">vamshisiddarth/argus</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

---

## :material-rocket-launch-outline: Quick start

=== "Local scan"

    ```bash
    pip install argus-cloud-optimizer

    # Configure — set your API key and enable dry-run
    export ANTHROPIC_API_KEY=sk-ant-...
    export DRY_RUN=true

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

<div class="cta-strip">
  <h2>Ready to find what's wasting money?</h2>
  <p>Clone, configure, deploy. First scan in under 5 minutes. Free and open source.</p>
  <div class="cta-btns">
    <a href="getting-started/" class="md-button md-button--primary">Get Started</a>
    <a href="https://github.com/vamshisiddarth/argus" class="md-button">View on GitHub</a>
  </div>
</div>

## :material-rocket-launch-outline: What's next

<div class="feature-grid" markdown>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-database-outline:</div>

**Resource Registry**

A single declarative source of truth for every resource type — makes adding new types and clouds a one-file change.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-wrench-outline:</div>

**Remediation v1**

Act on findings directly from Slack — approve a deletion, stop an idle instance, release an unassociated IP.
</div>

<div class="feature-card" markdown>
<div class="icon" markdown>:material-chart-timeline:</div>

**Historical Tracking**

Week-over-week comparison of findings — see what's new, what's resolved, and what keeps coming back.
</div>

</div>

[See the full roadmap](roadmap.md){ .md-button }

<script>
/* ── Terminal typewriter ─────────────────────────────────── */
(function(){
  /* Rich HTML lines — inline styles beat any MkDocs theme overrides */
  var C={
    ps:  'color:#61afef;font-weight:700',
    arr: 'color:#636d83',                    /* arrows — visible but muted */
    em:  'color:#e5c07b;font-weight:600',
    rn:  'color:#61afef;font-weight:600',    /* resource name */
    rt:  'color:#7a8394',                    /* resource type */
    dim: 'color:#636d83',                    /* dim scanning text */
    hdr: 'color:#e5e9f0;font-weight:700',
    tot: 'color:#e5c07b;font-weight:700',
    dot_h:'color:#e06c75;font-size:1.1em',
    dot_m:'color:#e5c07b;font-size:1.1em',
    res: 'color:#abb2bf;font-weight:600',
    typ: 'color:#7a8394',
    c_h: 'color:#e06c75;font-weight:700',
    c_m: 'color:#e5c07b;font-weight:700',
    kw:  'color:#56b6c2;font-weight:700',    /* RIGHT-SIZE / DELETE */
    sav: 'color:#98c379;font-weight:600',
    mut: 'color:#7a8394',
    sep: 'color:#4a5263',                    /* separator dots */
  };
  function s(style,text){ return '<span style="'+style+'">'+text+'</span>'; }

  var LINES=[
    /* 0: prompt — typed char by char */
    {t:'gap'},
    {t:'html',h: s(C.arr,'◈ ')+'Scanning '+s(C.em,'47')+' resources across '+s(C.em,'4')+' AWS regions'+s(C.dim,'...')},
    {t:'html',h: s(C.arr,'  →')+' '+s(C.rn,'db-analytics-01')+' '+s(C.sep,'·')+' '+s(C.rt,'RDS db.r5.4xlarge')+' '+s(C.dim,'· checking')},
    {t:'html',h: s(C.arr,'  →')+' '+s(C.rn,'cache-prod-001')+' '+s(C.sep,'·')+' '+s(C.rt,'ElastiCache r6g.large')+' '+s(C.dim,'· 0 connections')},
    {t:'html',h: s(C.arr,'  →')+' '+s(C.rn,'nat-0def456')+' '+s(C.sep,'·')+' '+s(C.rt,'NAT Gateway')+' '+s(C.dim,'· 847 bytes/month')},
    {t:'gap'},
    {t:'html',h: s(C.dot_h,'◆')+' '+s(C.hdr,'3 high-priority findings')+' '+s(C.sep,'·')+' '+s(C.tot,'$1,410/mo')+' '+s(C.mut,'estimated waste')},
    {t:'gap'},
    {t:'html',h: s(C.dot_h,'●')+' '+s(C.res,'db-analytics-01')+' '+s(C.typ,'RDS db.r5.4xlarge')+' '+s(C.c_h,'$1,240/mo')},
    {t:'html',h: '  '+s(C.kw,'RIGHT-SIZE:')+' '+s(C.typ,'db.r5.4xlarge → db.r5.xlarge')+' '+s(C.sav,'saves $920/mo')},
    {t:'html',h: s(C.dot_h,'●')+' '+s(C.res,'cache-prod-001')+' '+s(C.typ,'ElastiCache r6g.large')+' '+s(C.c_h,'$142/mo')},
    {t:'html',h: '  '+s(C.kw,'DELETE:')+' '+s(C.typ,'Zero cache hits in 30 days.')},
    {t:'html',h: s(C.dot_m,'◉')+' '+s(C.res,'nat-0def456')+' '+s(C.typ,'NAT Gateway')+' '+s(C.c_m,'$28/mo')},
    {t:'html',h: '  '+s(C.kw,'DELETE:')+' '+s(C.typ,'847 bytes in 90 days. Orphaned.')},
  ];

  var PROMPT="What's wasting the most money this week?";

  function run(body){
    if(body._argus_started) return;
    body._argus_started=true;

    /* prompt line */
    var pl=document.createElement('div');
    pl.style.cssText='color:#e5e7eb';
    var typed=document.createElement('span');
    var cur=document.createElement('span');
    cur.className='ht-cursor';
    pl.innerHTML=s(C.ps,'argus&gt; ');
    pl.appendChild(typed);
    pl.appendChild(cur);
    body.appendChild(pl);

    var ci=0;
    function typeChar(){
      typed.textContent=PROMPT.slice(0,++ci);
      if(ci<PROMPT.length) setTimeout(typeChar,38);
      else { cur.style.display='none'; setTimeout(function(){showLine(0,0);},380); }
    }

    function showLine(idx,delay){
      if(idx>=LINES.length)return;
      setTimeout(function(){
        var s2=LINES[idx];
        if(s2.t==='gap'){
          var g=document.createElement('div');
          g.style.height='0.5em';
          body.appendChild(g);
          showLine(idx+1,50);
        } else {
          var el=document.createElement('div');
          el.innerHTML=s2.h;
          body.appendChild(el);
          var d=110;
          showLine(idx+1,d);
        }
      },delay);
    }

    setTimeout(typeChar,600);
  }

  function tryRun(attempts){
    var body=document.getElementById('ht-body');
    if(body){ run(body); }
    else if((attempts||0)<25){ setTimeout(function(){ tryRun((attempts||0)+1); },80); }
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',function(){ tryRun(); });
  } else {
    tryRun();
  }
  /* MkDocs Material instant navigation */
  if(typeof document$!=='undefined'){
    document$.subscribe(function(){ tryRun(); });
  }
})();

/* ── Stat counters ───────────────────────────────────────── */
(function(){
  function animCount(el){
    var raw=el.getAttribute('data-count');
    if(!raw||el._counted)return;
    el._counted=true;
    var prefix=el.getAttribute('data-prefix')||'';
    var suffix=el.getAttribute('data-suffix')||'';
    var target=parseFloat(raw);
    var isFloat=raw.indexOf('.')!==-1;
    var t0=performance.now(), dur=900;
    function step(now){
      var p=Math.min((now-t0)/dur,1);
      var ease=1-Math.pow(1-p,3);
      var v=target*ease;
      el.textContent=prefix+(isFloat?v.toFixed(2):Math.round(v))+suffix;
      if(p<1) requestAnimationFrame(step);
      else el.textContent=prefix+(isFloat?target.toFixed(2):target)+suffix;
    }
    requestAnimationFrame(step);
  }
  function initCounters(){
    var obs=new IntersectionObserver(function(entries){
      entries.forEach(function(e){ if(e.isIntersecting) animCount(e.target); });
    },{threshold:0.1});
    document.querySelectorAll('[data-count]').forEach(function(el){ obs.observe(el); });
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',initCounters);
  } else {
    initCounters();
  }
  if(typeof document$!=='undefined'){
    document$.subscribe(function(){ initCounters(); });
  }
})();
</script>
