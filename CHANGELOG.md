# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## v0.3.0 (2026-06-21)

### Added

- **Interactive chat mode** — `argus chat --cloud aws` starts a conversational REPL for cloud cost Q&A. Ask natural language questions about your infrastructure, get answers backed by real metrics and cost data. Supports multi-turn follow-ups.
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
- **75 new unit tests** for ChatSession, cloud auto-detection, and adapter coverage.

### Changed

- CLI restructured to use subcommands. `argus --run-now` still works but `argus scan` is the canonical form.
- `--cloud` no longer defaults to `aws` — auto-detected from env vars, or errors with a clear message if undetectable.
- Right-sizing rules and priority thresholds extracted into shared constants used by both batch and chat prompts.
- History trimming now uses a cheap LLM call to summarize dropped messages instead of a static placeholder, with automatic fallback on failure.
- Error handling in `ChatSession.ask()` catches specific exception types (network, parse, provider errors) with targeted messages instead of a bare `except Exception`.
- `/scan` command now tells the user to run `argus scan` instead of hacky internal entrypoint calls.
- REPL supports arrow keys, input history (via readline), and multi-line input (trailing backslash continuation).
- Chat demo (`examples/chat_demo.py`) accepts `--cloud` flag and uses cloud-appropriate resource types.
- Quickstart docs show tabbed setup for AWS, GCP, and Azure.
- Test count: 431 → **511**.

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
