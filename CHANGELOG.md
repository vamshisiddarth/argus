# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

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
