# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## v0.7.0 (2026-10-22)

A trust release. Argus now tells you what it covered, fails loudly when it could not do its job, and stops presenting missing data as evidence. Prompted by a real-user run on v0.6.1; see the upgrade notes for behaviour that changes.

### Behaviour changes

- **A scan whose model never submits findings now fails** with exit code 3 instead of exiting 0 with zero findings. Argus reminds the model once to call `submit_findings`; a second miss raises `AgentDidNotSubmitError`. An explicit empty submission is still a valid clean scan.
- **AWS preflight can stop a scan** with exit code 4 before any LLM budget is spent: no Resource Explorer aggregator index (a local-only index silently searched one region) or no Search permission. A missing default view is a warning (results carry no tags). `--skip-preflight` / `ARGUS_SKIP_PREFLIGHT=true` bypasses it and is recorded in the report. In multi-account runs one failing account is recorded in `scan_errors` and the others continue.
- **`--lookback-days` is now actually applied.** The prompt and tool schema used to tell the model never to use less than 90 days, so the model asked for 90 whatever you set. The configured window now overrides every metrics query.
- **The resource cap no longer drops whole resource types.** With no cost data the old selection was arbitrary; selection is now a deterministic round-robin across types (cost order with a per-type floor when costs exist).

### Added

- **Report schema 1.1.0** (additive): `coverage` (discovered / analysed / dropped / truncated, per-type and regions), `scan_window` (the lookback window used and whether costs are billed), `preflight` (per-account check results). Findings gain `confidence` (low / medium / high) and `cost_basis` (billed / estimated).
- **Coverage in every output:** the HTML report header, a stderr summary line from `argus scan`, and the scan result. `--strict-coverage` / `STRICT_COVERAGE=true` makes truncation a failure (exit 1).
- **Preflight checks P1 to P7** (identity and admin-role warning, Resource Explorer reachability, aggregator index, index state, default view, `tags` in the view, Search permission). Each failure names the fix.
- **No data is not zero:** metric results carry `status` (`ok` / `no_data` / `error`) and an explicit "unavailable, not zero" note; the AWS adapter no longer reports a permission error as "no data". Findings backed by unavailable metrics are forced to `confidence: low`, and windows under 90 days cap confidence at `medium`.
- Exit codes documented in a new reference page. `docs/reference/troubleshooting.md` explains each preflight code.
- IAM: `GetDefaultView`, `ListViews`, `GetIndex` added to the CloudFormation templates and docs; Terraform read-only scan role in `deploy/aws/terraform/`; the AWS template exposes `ResourceExplorerRegion`.

### Fixed (from customer live runs)

- **Output truncation:** `max_tokens` was hard-coded to 4096 and a cut-off scan failed with no way forward. It is now `AI_MAX_TOKENS` (default 16000). When the model is cut off, Argus asks it to submit findings in batches (`submit_findings` accepts `partial`), and fails with exit code 3 naming the setting after 3 cut-offs.
- **Anthropic timeouts:** the 60 second timeout is now `AI_TIMEOUT_SECONDS` (default 600) and timeouts and connection errors are retried.
- **Dependency:** `anthropic` is now `>=0.40.0,<3`, and `temperature` is only sent when the installed SDK accepts it (SDK 1.x/2.x reject it, which crashed fresh installs on the first model call).
- **Cost Explorer:** resource-level cost requests are clamped to 14 days (the most that exists); the "enable resource-level data in the PAYER account" error no longer shows the wrong IAM hint; each failure is logged once; a new preflight check P8 warns before any LLM spend that cost data will be unavailable.
- **Finding tags** now come from the discovered inventory, not from the model (a model that omitted tags made `environment:prod` / `argus-exempt` safeguards silently inert).
- Dry runs no longer log `slack_delivered: true`.
- The AWS template did not expose `RESOURCE_EXPLORER_REGION`.
- The prefilter log field `dropped_zero_cost` was wrong whenever dropped resources had a cost; it is now `dropped`.

### Added after customer live runs

- **Confidence-split totals:** the report carries `waste_by_confidence` and `total_is_estimate`; the HTML, Slack digest and slide export label the headline as "not billed" with the split by confidence whenever any finding is not billed.
- **Deterministic baseline rules** for idle NAT gateways and Application / Classic load balancers (`docs/concepts/baseline-rules.md`). They run before the model over every discovered resource of those types (independent of the resource cap), win over model findings for the same resource, and make those findings repeatable run to run. Findings carry `detected_by`. `ARGUS_BASELINE_RULES=false` turns them off.
- **Per-region discovery:** when the first Resource Explorer search returns the 1,000-result maximum, Argus searches region by region and merges by ARN. `coverage.discovery_complete` is `false` only if a single region still overflows; `--strict-coverage` also fails on that.
- **Budget-scaled resource cap:** unless `MAX_RESOURCES_PER_SCAN` / `--max-resources` is set, the cap is 150 per dollar of LLM budget (50 to 1000; 300 at the default). The report records the cap and its source.
- **`--expect-account` / `ARGUS_EXPECT_ACCOUNT`:** abort with exit code 4 before any cloud or LLM call when single-account credentials belong to a different account (it also applies with `--skip-preflight`).
- **Configurable day windows:** besides `--lookback-days` (metrics), `--cost-days` / `COST_LOOKBACK_DAYS` sets the per-resource cost window (capped at 14 on AWS, where resource-level data ends) and `--activity-days` / `ACTIVITY_LOOKBACK_DAYS` sets the last-activity window (capped at 90, the CloudTrail maximum). The model cannot override them, and `scan_window` records the effective values.
- **Minimal read-only role:** `deploy/aws/read-only-scan-role.yaml` (minimal policy, or `ReadOnlyAccess` plus the Resource Explorer and Cost Explorer actions).
- `AI_MAX_TOKENS` now applies to every provider (Vertex AI and Azure OpenAI are clamped to their default models' output limits) and `BEDROCK_MAX_TOKENS` is no longer ignored.
- GCP and Azure scans return a result summary, so `argus scan` prints the coverage line for them too; GCP/Azure metric query failures are reported as errors, not as "no data".
- A failed `--strict-coverage` check no longer discards the report: it is written and delivered first, and a budget abort (exit code 2) takes precedence.
- Every `argus scan` option works before or after the `scan` subcommand (previously the subcommand's defaults overwrote values given before it).
- Preflight: an unreadable index state (`GetIndex` denied) is a warning, and missing credentials are named instead of blamed on `ListIndexes`.
- Chat mode uses the configured metrics window in its tool descriptions and metric display.
- The multi-cloud merged report carries `scan_window` and `preflight`.
- Tests no longer write reports or the audit log into the repository's `local_reports/`.

### Known limitations

- Baseline rules cover three resource types today; everything else is still judged by the model, so findings for other types can vary between runs.
- Resource Explorer region-by-region search still cannot see more than 1,000 resources in a single region (reported as `discovery_complete: false`).
- The budget-scaled cap is a heuristic from one measured run; a scan on very large resources can use more of the budget, and a budget abort returns the rule findings plus a summary but no model findings.
- Anthropic requests are not streamed; `AI_TIMEOUT_SECONDS` (default 600) bounds a response and `AI_MAX_TOKENS` above roughly 21000 may be rejected by the SDK's non-streaming guard.

### Upgrade notes

- Automations that treated exit code 0 as "scan ran" will now see 3 or 4 on the failures above. Handle them or investigate the underlying setup.
- Preflight is AWS-only in this release; GCP and Azure get coverage, window and no-data handling but no preflight.
- Known limitation: Resource Explorer `Search` returns at most 1,000 results, so on larger accounts `coverage.discovered` can understate the inventory. Argus now logs `resource_explorer_search_limit` when it hits the limit.
- `MAX_RESOURCES_PER_SCAN` no longer defaults to 200; it follows the LLM budget unless you set it (300 at the default budget).
- Scans with `--lookback-days` below 90 now really use that window; expect lower confidence on idle findings.

## v0.6.1 (2026-09-27)

### Fixed

- **`argus scan` crashed for `pip install` users** — the PyPI package didn't include the `integrations/` package, and v0.6.0 imports it (via `entrypoints/_remediation.py`) at the end of every scan. The scan ran the full AI analysis, then failed with `ModuleNotFoundError: No module named 'integrations'` before sending notifications. Lambda, Cloud Run, and Azure Function deploys were not affected (they ship the whole repository). The same missing package also broke `argus policies apply --confirm` for pip users since v0.5.0. `integrations` is now packaged, and a test fails if any top-level package is left out of the wheel.

## v0.6.0 (2026-09-27)

### Breaking

- **Automatic remediation is now opt-in.** Scans create Jira tickets only when `REMEDIATION_ENABLED=true` (default `false`). If you run v0.5.0 with Jira configured and want tickets to keep flowing after upgrade, set `REMEDIATION_ENABLED=true`. When Jira env vars are set but the flag is off, each scan logs `remediation_skipped reason=disabled` at INFO with a hint. `argus policies apply --confirm` is unaffected.

### Fixed

- **Policy `exclude` tags required every entry to match** — a resource was only excluded if it carried *all* listed exclude tags at once. With the bundled policies' `environment: [prod, production]` + `argus-exempt: ["true"]` excludes, prod resources without `argus-exempt`, and `argus-exempt` resources outside prod, still got tickets. Matching any one exclude entry now excludes the resource (`include` still requires every entry). Regression tests cover the shipped policies.
- **`accounts` scope filters never matched** — findings didn't carry an account ID, so `include: accounts` matched nothing and `exclude: accounts` excluded nothing. Findings now record `account_id` / `account_name` (from the scanned account, or the Azure subscription in the resource ID), and runbooks get the real account ID.
- **Every re-scan commented on every open Jira ticket** — the snapshot fingerprint included the per-scan `proposal_id`, so nothing ever looked unchanged. The fingerprint now covers only cost, priority, and AI reasoning; tickets created by v0.5.0 are handled too.
- **`aws-rds-resize-high-cost-idle` lacked the `argus-exempt` exclude** that every other bundled policy has.
- **CLI and scheduled scans read different policy-folder variables** — `argus policies validate/plan/apply` read `ARGUS_POLICIES_DIR` while the post-scan runner read `ARGUS_POLICY_DIR`, so `plan` could preview one set of policies and the scan use another. Both now resolve the folder the same way: `ARGUS_POLICY_DIR`, then `ARGUS_POLICIES_DIR` (still accepted), then `./config/policies`. A warning is logged if both are set to different values.
- **Remediation ignored `DRY_RUN`** — `argus scan --dry-run` and `DRY_RUN=true` skipped Slack delivery but still created and commented on real Jira tickets when Jira credentials were set. Dry runs now evaluate policies and log a `remediation_would_track` line per proposal, with no Jira calls.

### Changed

- Report schema is now **1.0.1**: findings include optional `account_id` and `account_name`.
- Remediation runner now ends every run with one `remediation_summary` log line (`findings`, `proposals`, `tracked`, `failed`, `dry_run`), and each failed ticket logs its `policy_id` and `error_type` alongside the `resource_id`. A run that fails outright logs `remediation_aborted` with `error_type`; a traceback is attached only for unexpected errors, not for Jira/config `TrackerError`s.

## v0.5.0 (2026-07-05)

### Added

- **Remediation engine** (`core/remediation/`) — policy-driven proposal system that matches AI findings against YAML policies and generates prioritised change proposals.
  - Two-tier condition matching: Tier 1 (cost, AI priority, idle days — universal), Tier 2 (metric conditions — registry-known types only).
  - Weight-ordered evaluation: highest-weight policy wins per resource; lower-weight policies act as catch-alls.
  - Deduplication: one proposal per `resource_id` per scan, regardless of how many findings reference the same resource.
  - Proposal UUID (`proposal_id`) for end-to-end traceability.
- **Policy loader & validator** — YAML-driven policy files with deep validation: registry action cross-check (invalid action for resource type fails at load time), duplicate ID detection, weight-conflict detection, shadowed-policy warnings.
- **Jira integration** (`integrations/jira/`) — full ticket lifecycle: create (idempotent via label dedup), diff-comment on re-scan, ADF-structured description with metrics table, runbook code block, and snapshot fingerprint.
- **JSONL audit log** (`core/remediation/audit.py`) — every `apply --confirm` writes a line to `local_reports/audit.jsonl` mapping `proposal_id → jira_key → jira_url`. Path overrideable via `ARGUS_AUDIT_LOG` env var.
- **Rightsizing recommendations** (`core/remediation/rightsizing.py`) — `resize` and `reduce_nodes` proposals include a specific target tier or node count derived from observed CPU% (e.g., "Recommend db.t3.small — CPU ~8%"). Shown in CLI plan table and Jira Recommendation section.
- **13 bundled policies** in `config/policies/` covering all three clouds:
  - AWS: EC2 stop, RDS resize, EBS delete, ELB delete, ElastiCache delete, Lambda delete, Redshift snapshot-delete
  - GCP: Compute stop, Cloud SQL stop, GKE reduce-nodes
  - Azure: VM stop, SQL resize, AKS reduce-nodes
- **CLI** — `argus policies validate / plan / apply / docs / stats` fully implemented.
  - `plan` output: sorted table with cost-per-resource, rightsizing hints, total savings estimate, and Jira ticket preview.
  - `apply --confirm` creates/updates tickets and prints per-ticket status.
  - `stats` reads `audit.jsonl` and reports per-policy proposal counts, Jira new/update split, and cloud breakdown for a configurable `--days` window.
- **CONTRIBUTING.md** — new "Adding a remediation policy" section with step-by-step guide, policy YAML reference, and safety rules.
- **ARCHITECTURE.md** — remediation flow diagram, rightsizing module table, safety layers, future UI design note.
- **README** — remediation section with quick-start flow, bundled policy table, and safety guarantees.
- 101 new tests (engine dedup, scope edge cases, ADF formatter, tracker lifecycle, audit log, webhook, loader edge cases, validator, rightsizing heuristics, stats command). Total: 1756 tests.

### Changed

- `config/integrations.yaml` and `accounts.yaml` added to `.gitignore` (contain credentials/role ARNs).
- `_tier2_matches` — non-numeric metric values now fail the policy condition instead of silently skipping.
- Jira ticket summary now includes priority indicator: `[Argus] Stop idle-vm ($120/mo · high priority)`.
- Jira description uses proper ADF sections (headings, metrics table, code block) instead of a single text blob.
- `apply --confirm` description text updated (removed stale "Phase 3" reference).

---

## v0.4.1 (2026-06-28)

### Fixed

- **GCP Cloud SQL asset type** — corrected from `sql.googleapis.com/Instance` to `sqladmin.googleapis.com/Instance` in Asset Inventory, Cloud Monitoring, and Cloud Logging. Cloud SQL resources were missing from all GCP scans.
- **GCP INVALID_ARGUMENT on disabled APIs** — Cloud Asset Inventory now strips any asset type whose API is not enabled in the project and retries. Previously, a single disabled API (e.g., Bigtable, Spanner, AlloyDB) caused the entire scan to crash.
- **GCP Cloud Logging `timeout` kwarg** — removed unsupported `timeout=` parameter from `list_entries()` call; caused `TypeError` on current `google-cloud-logging` versions.
- **Budget exceeded exit code** — all entrypoints (CLI, Lambda, Cloud Run, Azure Function) now exit with code 2 when the scan budget is exceeded. Previously exited 0, making it impossible for orchestrators to detect the abort condition.
- **`RESOURCE_EXPLORER_REGION` ignored** — `AWSAdapter.for_account()` was always using `PRIMARY_REGION` as the aggregator region, silently ignoring the `RESOURCE_EXPLORER_REGION` env var. Accounts with an aggregator index outside `us-east-1` were scanned with the wrong region and got empty results.
- **Slack delivery failure swallowed** — `notify_all()` was catching all delivery errors, logging them, and returning normally (exit 0). Users had no way to know their weekly report never arrived. Now returns `False` when all providers fail; Lambda raises `RuntimeError` (CloudWatch marks invocation failed), Cloud Run and Azure Function exit with code 1.
- **Slack delivery decoupled from report upload** — all three entrypoints now wrap the storage upload (S3 / GCS / Blob) in a separate try/except so Slack digest fires even if the upload fails.
- **GCS v4 Signed URL on Cloud Run** — Cloud Run credentials carry no private key, causing signed URL generation to fail silently. The helper now passes `service_account_email` + short-lived `access_token` from ADC to `generate_signed_url()`, which uses the signBlob API instead of a local key.
- **Missing GCP dependencies** — `google-cloud-bigquery` and `google-cloud-storage` were absent from `requirements/gcp.txt`, causing billing queries and GCS report uploads to fail at runtime.
- **Missing Azure Function runtime** — `azure-functions` was absent from `requirements/azure.txt`; `function_app.py` and `host.json` (required by the v2 Python model) were missing from the repo entirely.
- **GCP deploy script** — `deploy/gcp/deploy.sh` was submitting the container build without `--build-arg CLOUD=gcp`, defaulting to the AWS image. Also added preflight checks for `gcloud` auth and ADC, and fixed `--args` so the Cloud Run Job runs `scan --cloud gcp` instead of `--help`.
- **AWS IAM** — added `cloudwatch:ListMetrics` to both `single-account/template.yaml` and `spoke-role.yaml`; without it, dynamic CloudWatch metric discovery was denied.

### Added

- 7 new unit tests covering the above fixes: `RESOURCE_EXPLORER_REGION` env var propagation, `notify_all()` return value and failure behaviour, entrypoint exit codes on delivery failure.
- 37 unit tests from the initial 0.4.1 batch: INVALID_ARGUMENT retry loop, NotFound → PermissionError mapping, timeout regression guard, and budget exit-code assertions.

---

## v0.4.0 (2026-06-24)

### Added

- **Interactive chat mode** — `argus chat --cloud aws` starts a conversational REPL for cloud cost Q&A. Ask natural language questions about your infrastructure, get answers backed by real metrics and cost data. Supports multi-turn follow-ups.
- **`/summary` command** — compact earlier conversation turns into a context summary on demand, freeing up token budget without losing context.
- **`format_tool_result()`** — all 4 tool outputs (`list_resources`, `get_metrics`, `get_cost`, `get_last_activity`) are now converted to compact human-readable summaries before the AI sees them; no raw JSON ever reaches the model or appears in responses.
- **Subcommand CLI** — `argus scan` (replaces `argus --run-now`) and `argus chat`. The `--run-now` flag still works as a backward-compatible alias.
- **Cloud auto-detection** — `--cloud` flag is now optional. Argus detects the cloud from environment variables: `GCP_PROJECT_ID` → gcp, `AZURE_SUBSCRIPTION_IDS` → azure, AWS credentials → aws. Explicit `--cloud` always takes priority.
- **Per-session token budget** — chat mode defaults to $1.00/session (configurable via `--llm-budget`). Per-turn and cumulative cost displayed after every response.
- **REPL commands** — `/help`, `/scan`, `/cost`, `/clear`, `/quit` for session management.
- **Token-based history trimming** — conversation history automatically trimmed when approaching context limits, with context summary for continuity.
- **Tool call status feedback** — REPL shows which tools are being called during analysis (e.g., "Get Metrics: nat-0abc123...").
- **Optional `rich` formatting** — `pip install argus-cloud-optimizer[chat]` adds spinner, dimmed cost footers, and styled banners. Falls back to plain text without it.
- **Sample reports for all clouds** — `examples/sample-report-gcp.json` and `examples/sample-report-azure.json` alongside the existing AWS report.
- **GCP adapter expansion** — 15 new resource types with curated metric mappings: Cloud NAT, Forwarding Rules, Backend Services, VPN Tunnels, Serverless VPC Connectors, Bigtable, AlloyDB, Filestore, Memorystore Memcached, Firestore, Cloud Composer, Vertex AI Workbench, App Engine, Cloud Tasks, Static IPs. Discovery: 22 → 31 types. Metrics: 16 → 31 types.
- **Azure adapter expansion** — 14 new resource types with curated metric mappings: NAT Gateway, VPN Gateway, Azure Firewall, Front Door, ExpressRoute, Public IPs, MySQL/PostgreSQL/MariaDB Flexible Servers, Synapse SQL Pools, ML Online Endpoints, Batch, IoT Hub, SignalR. Metrics: 26 → 40 types.
- **GCP multi-project support** — scan multiple GCP projects in a single run. Set `GCP_PROJECT_IDS=proj-a,proj-b` or use `accounts.yaml` with a `projects` key. One adapter + agent loop per project, findings aggregated across all projects.
- **Azure multi-subscription via `accounts.yaml`** — `ACCOUNTS_CONFIG` JSON or `accounts.yaml` `subscriptions` key now supported alongside `AZURE_SUBSCRIPTION_IDS` env var. Named subscriptions appear in reports.
- **Multi-cloud `accounts.yaml`** — single config file supports all three clouds: `accounts` (AWS), `projects` (GCP), `subscriptions` (Azure). `--accounts` flag works for all clouds, not just AWS.
- **107 new unit tests** — ChatSession, cloud auto-detection, multi-project/subscription, adapter coverage, and chat polish (formatters, turn grouping, `force_summarize`).

### Changed

- **Chat spinner updates live** — the status message changes as each tool fires (`Scanning resources...` → `Fetching metrics: i-0abc123...`) instead of showing a static "Thinking..." throughout.
- **History trim is turn-safe** — `_trim_history` now drops complete user/assistant/tool-result turns atomically; tool-call and tool-result messages are never split across a trim boundary.
- **Welcome banner** now shows session budget and the `\` multi-line input tip.
- **`load_resources` failures** produce a cloud-specific actionable hint (`aws configure`, `gcloud auth`, `az login`) instead of an unhandled exception.
- **Rate limit and auth errors** from the AI provider produce distinct user-facing messages instead of a generic `RuntimeError`.
- CLI restructured to use subcommands. `argus --run-now` still works but `argus scan` is the canonical form.
- `--cloud` no longer defaults to `aws` — auto-detected from env vars, or errors with a clear message if undetectable.
- Right-sizing rules and priority thresholds extracted into shared constants used by both batch and chat prompts.
- History trimming now uses a cheap LLM call to summarize dropped messages instead of a static placeholder, with automatic fallback on failure.
- Error handling in `ChatSession.ask()` catches specific exception types (network, parse, provider errors) with targeted messages instead of a bare `except Exception`.
- `/scan` command now tells the user to run `argus scan` instead of hacky internal entrypoint calls.
- REPL supports arrow keys, input history (via readline), and multi-line input (trailing backslash continuation).
- Chat demo (`examples/chat_demo.py`) accepts `--cloud` flag and uses cloud-appropriate resource types.
- `--accounts` flag now works for GCP and Azure (previously AWS only).
- Startup validation accepts `GCP_PROJECT_IDS` and `ACCOUNTS_CONFIG` as alternatives to single-project/subscription env vars.
- Test count: 431 → **538**.

### Documentation

- **Homepage diagram** — replaced mermaid with a custom inline SVG: outputs below the agent with orthogonal connectors, horizontal tool arrows, no line overlaps; all text fits within box boundaries.
- **Sun/moon pill toggle** — replaced Material's default toggle icon with a polished animated pill in the header.
- **Dynamic version badge** — hero badge version now fetched live from GitHub Releases API; no manual updates needed.
- **Reference accuracy fixes** — removed non-existent `BEDROCK_TEMPERATURE` var; corrected Azure `Monitoring Reader` scope to per-subscription; removed stale "Phase 8 —" prefix from security model table; added missing Security Model and Troubleshooting links to reference index.
- **Quickstart fix** — corrected `GCP_BILLING_TABLE` → `BILLING_BQ_TABLE`.
- **Configuration page** — added scan tuning section (`MAX_RESOURCES_PER_SCAN`, `METRICS_LOOKBACK_DAYS`, `MAX_AGENT_ITERATIONS`, `LLM_BUDGET_USD`) with pointer to full env-vars reference.
- **README** — replaced Slack screenshot with current text digest format matching the docs home page.

---

## v0.2.0 (2026-06-19)

### Added

- **PyPI packaging** — `pip install argus-cloud-optimizer` installs all three clouds in one package. `argus` CLI entrypoint replaces `python main.py`.
- **LLM token/cost tracking** — every scan logs input/output tokens and estimated LLM cost. Reports include `agent_input_tokens`, `agent_output_tokens`, and `estimated_agent_cost_usd`.
- **Hard budget enforcement** — `--llm-budget` flag (default: $2.00/scan) stops the agent if LLM cost exceeds the limit. Set to 0 for unlimited.
- **Centralized config** — `pydantic-settings` config layer with env var validation on startup. All settings documented in `.env.example`.
- **Secret manager integration** — AWS Secrets Manager, GCP Secret Manager, and Azure Key Vault support for storing API keys and webhook URLs.
- **CLI flags** — `--max-resources`, `--lookback-days`, `--llm-budget`, `--version`/`-V`.
- **Integration test layer** — 32 tests behind `@pytest.mark.integration`: adapter contract tests, report schema validation, Slack payload structure, scan comparison. Run with `make test-integration`.
- **Publish workflow** — GitHub Actions trusted publisher for PyPI releases.
- **Example report** — `examples/sample-report-aws.json` with realistic findings and AI reasoning.
- **Limitations & parity docs** — honest limitations table and multi-cloud parity matrix in README.

### Changed

- Python requirement relaxed from 3.13 to **3.11+** (CI tests 3.11/3.12/3.13).
- All cloud SDKs moved into core dependencies — no extras needed for basic usage.
- Test count: 208 → **463** (431 unit + 32 integration).

### Fixed

- **azure-monitor-query v2.0 breaking change** — pinned to `>=1.4.0,<2.0.0` to avoid removed `MetricAggregationType` and `MetricsQueryClient`.
- PEP 639 license classifier conflict with setuptools.
- CLI smoke tests for all three clouds now pass end-to-end.

---

## v0.1.0 (2026-06-15)

Initial release.

### Features

- **Multi-cloud support** — AWS, GCP, and Azure adapters with a shared four-method contract (`list_resources`, `get_metrics`, `get_cost`, `get_last_activity`)
- **AI-driven analysis** — ReAct agent loop powered by Claude (Anthropic API, AWS Bedrock, Vertex AI, or Azure OpenAI); no hardcoded idle thresholds
- **AWS adapter** — Resource Explorer for discovery, CloudWatch for metrics (43 resource types + dynamic fallback), Cost Explorer for cost data, CloudTrail for last-activity timestamps
- **GCP adapter** — Cloud Asset Inventory (22 asset types), Cloud Monitoring, BigQuery billing export, Cloud Audit Logs
- **Azure adapter** — Resource Graph (KQL, cross-subscription), Azure Monitor (25 resource types), Cost Management, Activity Log
- **Multi-account AWS** — STS AssumeRole with hub/spoke IAM architecture; one scan covers unlimited accounts
- **Slack delivery** — weekly report with findings ranked by monthly waste, AI-written explanations and recommendations
- **SAM deployment** — `sam build && sam deploy --guided` deploys to AWS Lambda in minutes; no manual S3 setup
- **Docker support** — `docker build --build-arg CLOUD=aws -t argus .` for container-first usage
- **208 tests** — all pass offline with no real cloud credentials required
