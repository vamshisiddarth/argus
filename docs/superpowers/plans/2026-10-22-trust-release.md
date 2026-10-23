# Argus v0.7.0 Trust Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Argus reports honest about what they covered and fail loudly when the environment or the model produced nothing usable, then release it as v0.7.0.

**Architecture:** Cloud-agnostic pieces live in `core/` (selection, coverage, errors, finding confidence, prompt/window handling) and are carried by `AgentLoop` as attributes (`loop.coverage`, `loop.scan_window`) next to the existing `loop.tracker`. The AWS-only preflight lives in `adapters/aws/preflight.py` and runs in the Lambda/CLI entrypoint before `AgentLoop.run`. Report schema moves 1.0.1 to 1.1.0 by adding optional keys only.

**Tech Stack:** Python 3.11+, boto3, pytest, structlog, ruff + black (repo CI), mkdocs docs.

**Spec:** `DESIGN_trust_release.md` (sections 1 to 13, decisions in 12 and 13) and `HANDOFF_user_feedback.md`. Existing failing tests: `tests/core/test_trust_regressions.py`.

## Global Constraints

- Strictly read-only against cloud accounts. No new write calls. No `iam:List*` permission for the admin-role check (name/ARN heuristic only).
- Report `schema_version` becomes `"1.1.0"`. New keys are optional; no key is renamed or removed; `scan_diff` must still work between a 1.0.1 and a 1.1.0 report.
- Package version becomes `0.7.0` (`core/__version__.py`).
- Exit codes: `2` budget exceeded (unchanged), `3` agent stopped without `submit_findings` after one re-prompt, `4` preflight failed.
- `--skip-preflight` / `ARGUS_SKIP_PREFLIGHT=true`: logs WARNING, sets `preflight.skipped = true`, shown in CLI summary, never default.
- `confidence` is the string `"low" | "medium" | "high"`.
- The literal "90" must not remain as a hardcoded lookback in `core/agent/prompts.py`, tool schemas, or README prose about the scan window. The real value is injected from `get_settings().scan.metrics_lookback_days`.
- Selection must be deterministic: same inputs, same candidate set and order (ties broken by `resource_id`).
- Truncation (`dropped > 0`) warns by default. `--strict-coverage` / `STRICT_COVERAGE=true` makes it a failure.
- Multi-account: one account failing preflight or the agent is recorded in `scan_errors` and the others continue. If every account fails, raise. 
- Repo style: line length 88, `ruff` and `black` clean, structlog for logging, no cloud SDK imports in `core/`.
- No attribution lines in commit messages.

## Review Focus

Failure modes the spec implies that no single task's main tests would catch; each has a test in the owning task.

1. Cap larger than discovered (no truncation): `truncated` is false, `dropped` is 0, no warning. (Task 3)
2. Zero resources discovered: coverage is all zeros, HTML header and CLI summary render without error. (Task 3)
3. `--lookback-days 14` while the model passes `days=90` in a tool call: the adapter still receives 14. (Task 4)
4. Model submits a finding that says "zero over N days" for a resource whose metrics had `has_data` false: confidence is forced to `"low"`. (Task 5)
5. Multi-account run where account A fails preflight and account B succeeds, and where all accounts fail. (Task 6)

## File Structure

| File | Responsibility |
|------|----------------|
| `core/errors.py` (new) | Exit code constants, `AgentDidNotSubmitError`, `PreflightFailedError` |
| `core/models/coverage.py` (new) | `Coverage`, `TypeCoverage`, merge, serialisation |
| `core/models/preflight.py` (new) | `PreflightCheck`, `PreflightResult` |
| `core/agent/selection.py` (new) | Deterministic candidate selection |
| `adapters/aws/preflight.py` (new) | AWS preflight checks P1 to P7 |
| `core/agent/loop.py` | Retry on no-submit, use selection, set coverage and scan window, force window, force confidence |
| `core/agent/prompts.py` | Inject real window; no-data rule; remove "never below 90" |
| `adapters/base.py`, `adapters/aws/cloudwatch.py`, `adapters/gcp/cloud_monitoring.py`, `adapters/azure/monitor.py` | `MetricSummary.status` / `error` |
| `core/models/finding.py` | Optional `confidence`, `cost_basis` |
| `core/reports/generator.py`, `multi_cloud.py`, `html.py` | Schema 1.1.0, coverage, window, preflight, confidence in output |
| `entrypoints/aws_lambda.py`, `gcp_cloudrun.py`, `azure_function.py`, `cli.py` | Wire preflight, coverage, exit codes, flags |
| `docs/`, `README.md`, `CHANGELOG.md`, `deploy/aws/` | Docs, IAM, CFN/Terraform snippet, exit codes |

---

### Task 1: Exit codes and the empty-result failure (#4)

**Files:**
- Create: `core/errors.py`
- Modify: `core/agent/loop.py` (the `else:` branch after `stop_reason == "tool_use"` in `AgentLoop.run`), `entrypoints/cli.py` (`_run_scan`), `tests/core/test_loop.py` (`test_end_turn_without_findings_returns_empty`)
- Test: `tests/core/test_trust_regressions.py` (`TestEmptyResultIsNotSuccess`, already written), `tests/entrypoints/test_cli_exit_codes.py` (new)

**Interfaces:**
- Produces: `EXIT_BUDGET_EXCEEDED = 2`, `EXIT_AGENT_NO_SUBMIT = 3`, `EXIT_PREFLIGHT_FAILED = 4` (ints); `class AgentDidNotSubmitError(RuntimeError)`; `class PreflightFailedError(RuntimeError)` with attribute `result` (typed in Task 6; for now `result: Any`).

- [ ] **Step 1: Run the two existing `TestEmptyResultIsNotSuccess` tests and confirm they fail** (`pytest tests/core/test_trust_regressions.py::TestEmptyResultIsNotSuccess -v`; expected: `DID NOT RAISE RuntimeError` and `[] == ['natgateway-0']`).
- [ ] **Step 2: Create `core/errors.py`** with the three constants and two exception classes above.
- [ ] **Step 3: Change `AgentLoop.run`.** On `end_turn` or `max_tokens` without `submit_findings`: if no retry has been used yet, append the assistant text as an assistant message plus a user message "You stopped without calling submit_findings. Call submit_findings now with your findings (an empty list if there are none).", set a local `retried = True` and continue the loop. If it happens again, raise `AgentDidNotSubmitError` whose message includes the model's last text (truncated to 500 chars). Keep logging `agent_stopped_without_findings`.
- [ ] **Step 4: Update `test_end_turn_without_findings_returns_empty`** in `tests/core/test_loop.py` to expect `AgentDidNotSubmitError` (the old assertion encoded the bug).
- [ ] **Step 5: Write `tests/entrypoints/test_cli_exit_codes.py`:** with `handler` patched to raise `AgentDidNotSubmitError("x")`, `_run_scan(args)` exits with `SystemExit` code `3`; with it raising `PreflightFailedError`, code `4`; with a result dict `{"budget_exceeded": True}`, code `2`. Message goes to stderr.
- [ ] **Step 6: Map the exceptions in `entrypoints/cli.py::_run_scan`** (try/except around the cloud dispatch; print message to stderr; `sys.exit(<code>)`). Add the exit codes to the `scan` subcommand epilog/help text.
- [ ] **Step 7: Run** `pytest tests/core tests/entrypoints -q`. Expected: all pass.
- [ ] **Step 8: Commit** `fix(agent): re-prompt once then fail when the model never submits findings (exit 3)`.

---

### Task 2: Deterministic candidate selection (#2)

**Files:**
- Create: `core/agent/selection.py`
- Modify: `core/agent/loop.py` (`_prefilter_resources`)
- Test: `tests/core/test_selection.py` (new), `tests/core/test_trust_regressions.py::TestSelectionWithoutCostData` (already written)

**Interfaces:**
- Produces: `HIGH_IMPACT_TYPES: frozenset[str]` (NAT Gateway, RDS DBInstance and DBCluster, ElastiCache CacheCluster and ReplicationGroup, ElasticLoadBalancingV2 LoadBalancer, EC2 Instance); `select_candidates(resources: list[Resource], costs: dict[str, float], cap: int) -> tuple[list[Resource], Literal["cost_desc", "stratified_by_type"]]`.

- [ ] **Step 1: Write `tests/core/test_selection.py`:**
  - `test_no_cost_data_round_robins_all_types`: 3 types x 4 resources, no costs, cap 6 returns 2 per type and `"stratified_by_type"`.
  - `test_cap_smaller_than_type_count_is_deterministic`: 5 types, cap 3 returns the first 3 types in sorted order, identical across 10 shuffles of the input list.
  - `test_high_impact_types_get_extra_picks_only_after_first_pass`: one high-impact type and two ordinary types, each with 10 resources, cap 7 returns 1 per type in pass one, then 2 picks per pass for the high-impact type (counts 3/2/2), and every type is present.
  - `test_with_cost_data_keeps_floor_per_type_then_fills_by_cost`: one type holds all the expensive resources, cap 6, all 3 types present, remaining slots filled by cost descending.
  - `test_cap_not_smaller_than_input_returns_everything`.
  - `test_ties_broken_by_resource_id`.
- [ ] **Step 2: Run, confirm they fail** (module missing).
- [ ] **Step 3: Implement `select_candidates`.** Cost branch (any cost > 0): reserve `min(count, 2)` per type in sorted-type order while the cap allows, fill the rest by cost descending then `resource_id`. No-cost branch: passes over sorted types; per pass, each type contributes 1 resource (2 if in `HIGH_IMPACT_TYPES` and this is not the first pass), taking resources in `resource_id` order, until the cap is reached or all resources are chosen.
- [ ] **Step 4: Use it in `_prefilter_resources`** in place of the sort-and-slice. Keep `costs` handling and the `cost_usd` payload entry. Rename the log field `dropped_zero_cost` to `dropped`. Store `self._selection = <rule>` and `self._all_resources = resources` for Task 3.
- [ ] **Step 5: Run** `pytest tests/core/test_selection.py tests/core/test_trust_regressions.py::TestSelectionWithoutCostData tests/core/test_loop.py -q`. Expected: pass.
- [ ] **Step 6: Commit** `fix(agent): never drop whole resource types when the cap truncates`.

---

### Task 3: Coverage block and schema 1.1.0 (#1)

**Files:**
- Create: `core/models/coverage.py`
- Modify: `core/agent/loop.py`, `core/reports/generator.py` (`build_report`, `SCHEMA_VERSION`), `core/reports/multi_cloud.py`, `core/reports/html.py`, `core/config.py` (`strict_coverage`), `entrypoints/aws_lambda.py`, `entrypoints/gcp_cloudrun.py`, `entrypoints/azure_function.py`, `entrypoints/cli.py`, `docs/reference/report-schema.md`
- Test: `tests/core/test_coverage.py` (new), additions to `tests/core/test_reports.py`, `tests/core/test_multi_cloud.py`, `tests/entrypoints/test_aws_lambda.py`

**Interfaces:**
- Consumes: `select_candidates` rule string from Task 2.
- Produces: `@dataclass TypeCoverage(discovered: int, analysed: int)`; `@dataclass Coverage(discovered: int, analysed: int, selection: str, cost_data_available: bool, regions_covered: list[str], types: dict[str, TypeCoverage])` with properties `dropped: int`, `truncated: bool`, method `to_dict() -> dict`, and `@staticmethod merge(items: list[Coverage]) -> Coverage` (sum counts, union regions, merge per-type maps, `selection` becomes `"mixed"` if rules differ). `AgentLoop.coverage: Coverage | None` set after prefilter. `build_report(..., coverage: dict | None = None, scan_window: dict | None = None, preflight: dict | None = None)`; report keys `coverage`, `scan_window`, `preflight` are always present (value `None` when not provided). `ScanMeta` dataclass in `entrypoints/_meta.py`: `ScanMeta(coverage: Coverage | None, scan_window: dict, preflight: dict | None)`; `_run_single_account` and `_run_multi_account` in `aws_lambda.py` gain a trailing `meta: ScanMeta` in their returned tuples (update all call sites and tests).

- [ ] **Step 1: Write `tests/core/test_coverage.py`:**
  - `test_dropped_and_truncated_flags` (880/200 gives dropped 680 and truncated true; 5/5 gives dropped 0 and truncated false).
  - `test_zero_resources_all_zero_and_not_truncated`.
  - `test_to_dict_has_documented_keys`.
  - `test_merge_sums_counts_unions_regions_merges_types`.
  - `test_merge_mixed_selection_rule`.
  - In `test_loop.py`: `test_loop_sets_coverage_after_prefilter` (FakeCloudAdapter gives discovered 1, analysed 1, regions `["us-east-1"]`).
- [ ] **Step 2: Run, confirm failures.**
- [ ] **Step 3: Implement `core/models/coverage.py`** and set `self.coverage` in `_prefilter_resources` (regions from the discovered resources; `cost_data_available` is true when any cost > 0). Emit a structured WARNING log `coverage_truncated` with the numbers and `MAX_RESOURCES_PER_SCAN` hint when `truncated`.
- [ ] **Step 4: Write report tests** in `tests/core/test_reports.py`: `build_report` output has `schema_version == "1.1.0"`, includes `coverage`, `scan_window`, `preflight` keys; a 1.0.1 fixture report diffed against it through `compare_scans` still works. HTML test: when `coverage.truncated` is true the HTML contains the text "Analysed 200 of 880" and a warning class; when `coverage` is `None` the HTML renders unchanged.
- [ ] **Step 5: Update `generator.py`** (`SCHEMA_VERSION = "1.1.0"`, new kwargs), `multi_cloud.py` (merge per-account coverage with `Coverage.merge`; keep per-account entries under `coverage_by_account`), and `html.py` (header block).
- [ ] **Step 6: Strict mode.** Add `strict_coverage: bool` to `ScanSettings` (`STRICT_COVERAGE`), CLI flag `--strict-coverage`. In the entrypoints, after the loop, if strict and `coverage.truncated`, raise `RuntimeError("Coverage truncated: analysed X of Y ...")` (exit 1). Test in `tests/entrypoints/test_aws_lambda.py`.
- [ ] **Step 7: Wire all three entrypoints** to pass `loop.coverage.to_dict()` into `build_report` via `ScanMeta`; print a one-line coverage summary in `cli.py` after the scan (`Coverage: analysed 200 of 880 (680 not analysed, selection=stratified_by_type)`).
- [ ] **Step 8: Update `docs/reference/report-schema.md`** with the new keys.
- [ ] **Step 9: Run** `pytest -q`. Expected: all pass.
- [ ] **Step 10: Commit** `feat(report): coverage block, schema 1.1.0, strict coverage flag`.

---

### Task 4: Honour the real lookback window and label cost basis (#3)

**Files:**
- Modify: `core/agent/loop.py` (`_execute`), `core/agent/prompts.py`, `adapters/aws/cloudwatch.py`, `README.md`, `docs/` pages that state a 90-day window, `core/models/finding.py` (`cost_basis`), `core/reports/html.py`
- Test: `tests/core/test_lookback.py` (new), additions to `tests/core/test_prompts.py` (create if absent)

**Interfaces:**
- Produces: `build_system_prompt(cloud, ignore_regions, accounts, lookback_days: int = 90)` (new keyword); `AgentLoop.scan_window: dict` with keys `metrics_lookback_days`, `cost_lookback_days`, `cost_basis` (`"billed" | "estimated" | "unavailable"`); `ResourceFinding.cost_basis: str | None = None`.

- [ ] **Step 1: Write `tests/core/test_lookback.py`:**
  - `test_loop_forces_configured_window_on_get_metrics` (`METRICS_LOOKBACK_DAYS=14`, the fake model calls `get_metrics` with `days=90`, the adapter mock receives `days=14`).
  - `test_loop_fills_days_when_model_omits_it`.
  - `test_prompt_contains_configured_window_and_no_hardcoded_90` (build prompt with `lookback_days=14`; assert "14" appears in the window sentence and the strings "Never set below 90" and "Do NOT pass a days value less than 90" are absent; the tool schema `days` description does not contain "90").
  - `test_prompt_warns_when_window_below_90` (prompt for 14 days tells the model to cap confidence at "medium" and mention the window in `waste_reason`).
  - `test_scan_window_cost_basis_unavailable_when_costs_empty`.
- [ ] **Step 2: Run, confirm failures.**
- [ ] **Step 3: In `_execute`**, for `get_metrics` set `arguments["days"] = settings.scan.metrics_lookback_days` unconditionally. Record `self.scan_window` in `run()` (cost window is the adapter default 30; `cost_basis` is `"billed"` if any cost was returned by `get_cost`, else `"unavailable"`).
- [ ] **Step 4: Rewrite the prompt text and the `get_metrics` tool schema** to take the window from `lookback_days` (decision thresholds line 11, step 3 of "YOUR APPROACH", tool descriptions at lines ~265 and ~283). Pass `lookback_days` from settings where `build_system_prompt` is called in `AgentLoop.run` and in `core/agent/chat.py`.
- [ ] **Step 5: `adapters/aws/cloudwatch.py`:** read the default via a function `default_metrics_days()` that reads settings at call time instead of the import-time constant `DEFAULT_METRICS_DAYS`; keep the constant as a thin alias so existing imports work.
- [ ] **Step 6: Findings get `cost_basis`:** `"billed"` when the resource id was present in the `get_cost` result, otherwise `"estimated"`; `to_dict`/`from_dict` carry it as an optional key; HTML shows a small "est." label for `"estimated"`.
- [ ] **Step 7: README and docs sweep:** `grep -rn "90" README.md docs/` and fix every line that states 90 days as the scan window so it says "default 90, set with `--lookback-days`". Add the real window next to the total in the HTML report header.
- [ ] **Step 8: Run** `pytest -q`. Expected: pass.
- [ ] **Step 9: Commit** `fix(agent): honour --lookback-days and stop hardcoding a 90-day window`.

---

### Task 5: No data is not zero, and confidence (#5)

**Files:**
- Modify: `adapters/base.py` (`MetricSummary`), `adapters/aws/cloudwatch.py` (the `ClientError` branch and the no-metric-defs branch), `adapters/gcp/cloud_monitoring.py`, `adapters/azure/monitor.py`, `core/agent/loop.py` (`_execute`, `_parse_findings`), `core/agent/prompts.py`, `core/models/finding.py`, `core/reports/html.py`, `core/reports/generator.py`
- Test: `tests/core/test_trust_regressions.py::TestNoDataIsNotZero` (already written), `tests/core/test_confidence.py` (new), `tests/adapters/aws/test_cloudwatch.py` (add)

**Interfaces:**
- Produces: `MetricSummary.status: Literal["ok", "no_data", "error"]` (default `"ok"`), `MetricSummary.error: str | None = None`; `to_dict()` adds `status`, `error` and, when status is not `"ok"`, `data_note` = `"metrics unavailable (<no data points returned | error: ...>); do not treat as zero usage"`. `ResourceFinding.confidence: str | None = None`.

- [ ] **Step 1: Write tests.**
  - `tests/adapters/aws/test_cloudwatch.py`: `test_access_denied_returns_status_error` (ClientError `AccessDenied` gives `status == "error"` and `has_data is False`, error text present); `test_no_datapoints_returns_status_no_data`; `test_data_present_returns_status_ok`.
  - `tests/core/test_confidence.py`: `test_no_data_finding_forced_to_low_confidence` (loop run where the fake adapter returns `has_data=False` for the resource and the model submits a finding with `confidence: "high"` and `waste_reason: "zero bytes over 90 days"`; resulting finding has `confidence == "low"`); `test_window_under_90_caps_confidence_at_medium`; `test_has_data_true_keeps_model_confidence`; `test_confidence_serialised_in_report_and_html`.
- [ ] **Step 2: Run, confirm failures.** (`TestNoDataIsNotZero` from the regressions file must also fail first.)
- [ ] **Step 3: Implement `status`/`error`/`data_note`** in `MetricSummary` (keep `has_data`; `status` derived from `has_data` when an adapter does not set it, so GCP and Azure keep working unchanged). In `cloudwatch.py` return `status="error"` with the error code and message on `ClientError`.
- [ ] **Step 4: Track no-data resources in the loop:** `_execute` records resource ids whose `get_metrics` result had `status != "ok"` in `self._no_data_ids`. In `_parse_findings` (add a `no_data_ids` parameter and `window_days`) force `confidence = "low"` for those, cap at `"medium"` when `window_days < 90`, otherwise keep the model's value (default `"medium"`).
- [ ] **Step 5: Prompt rule:** add to the system prompt and the `submit_findings` schema a `confidence` field (enum) and the rule "If get_metrics returns status other than ok, say 'no metric data' and never write zero usage."
- [ ] **Step 6: Show `confidence`** in the JSON (`to_dict`), HTML (badge) and Slack digest only if the existing formatter takes extra fields without change; otherwise leave Slack alone.
- [ ] **Step 7: Run** `pytest -q`. Expected: pass.
- [ ] **Step 8: Commit** `fix(agent): separate no-data from zero usage and add finding confidence`.

---

### Task 6: AWS preflight (#6, #7, #11)

**Files:**
- Create: `core/models/preflight.py`, `adapters/aws/preflight.py`
- Modify: `core/errors.py` (type `PreflightFailedError.result`), `entrypoints/aws_lambda.py`, `entrypoints/cli.py` (`--skip-preflight`), `core/config.py` (`skip_preflight`), `core/reports/html.py`
- Test: `tests/adapters/aws/test_preflight.py` (new), additions to `tests/entrypoints/test_aws_lambda.py`

**Interfaces:**
- Produces: `PreflightCheck(code: str, status: Literal["ok","info","warn","fail"], message: str, fix: str | None = None)`; `PreflightResult(account_id: str | None, checks: list[PreflightCheck], skipped: bool = False)` with `failed: list[PreflightCheck]`, `warnings: list[PreflightCheck]`, `to_dict()`; `run_preflight(session: boto3.Session, aggregator_region: str, account_id: str | None = None) -> PreflightResult`; `_is_admin_like(identity_arn: str) -> bool` (case-insensitive match on `administrator`, `fullaccess`, `admin` role-name segments).
- Check codes: `P1_IDENTITY`, `P2_RE_REACHABLE`, `P3_AGGREGATOR_INDEX`, `P4_INDEX_STATE`, `P5_DEFAULT_VIEW`, `P6_VIEW_TAGS`, `P7_SEARCH_PERMISSION`.

- [ ] **Step 1: Write `tests/adapters/aws/test_preflight.py`** with stubbed boto3 clients (`MagicMock`), one test per row:
  - identity ARN contains `AdministratorAccess` gives `P1` warn naming the ARN; read-only role gives `P1` info;
  - `ListIndexes` raises AccessDenied gives `P2` fail naming the missing action;
  - only a `LOCAL` index gives `P3` fail whose message contains "aggregator" and the region;
  - index `State == "CREATING"` gives `P4` warn;
  - `GetDefaultView` returns no view gives `P5` fail;
  - view `IncludedProperties` lacks `tags` gives `P6` warn mentioning `argus-exempt`;
  - `Search` AccessDenied gives `P7` fail listing the four actions;
  - all-good setup gives only ok/info checks and `failed == []`;
  - every fail has a non-empty `fix`.
- [ ] **Step 2: Run, confirm failures.**
- [ ] **Step 3: Implement `run_preflight`** with `sts.get_caller_identity`, `resource-explorer-2` `list_indexes`, `get_default_view`, `get_view`, and `search(QueryString="*", MaxResults=1)`. Message text names the aggregator region and the setting `RESOURCE_EXPLORER_REGION`. Each check runs independently; an exception in one becomes that check's `fail` and later checks that depend on it are skipped, not crashed.
- [ ] **Step 4: Wire into `aws_lambda.py`.** Single-account: run preflight before building the loop; if `failed` and not skipped, raise `PreflightFailedError(result)` (its message lists each failed check with its fix). Skipped: log WARNING, return `PreflightResult(skipped=True)`. Multi-account: run per account inside the existing try; a failed preflight is appended to `scan_errors` (add `"kind": "preflight"` and the check list) and the account is skipped; if no account succeeded raise `PreflightFailedError`. Pass the result dicts through `ScanMeta.preflight` into the report. Add `RESOURCE_EXPLORER_REGION` to the AWS SAM/CloudFormation template parameters (`deploy/aws/single-account/template.yaml`).
- [ ] **Step 5: Entrypoint tests:** `test_preflight_failure_raises_and_makes_no_ai_calls` (assert the fake AI provider's `chat` is never called); `test_skip_preflight_sets_flag_in_report`; `test_multi_account_one_preflight_failure_others_continue`; `test_multi_account_all_preflight_failures_raise`.
- [ ] **Step 6: CLI:** `--skip-preflight` flag (env `ARGUS_SKIP_PREFLIGHT`), print warnings and the skipped state at the top of scan output.
- [ ] **Step 7: HTML report** shows a "Setup warnings" box when `preflight` has warnings or `skipped`.
- [ ] **Step 8: Run** `pytest -q`. Expected: pass.
- [ ] **Step 9: Commit** `feat(aws): preflight checks for identity and Resource Explorer setup (exit 4)`.

---

### Task 7: Docs, IAM, release prep

**Files:**
- Modify: `docs/reference/iam-permissions.md`, `README.md` (IAM block near the `resource-explorer-2:Search` listing), `deploy/aws/single-account/template.yaml`, `deploy/aws/multi-account/spoke-role.yaml`, `docs/reference/env-vars.md`, `docs/reference/troubleshooting.md`, `docs/reference/report-schema.md`, `docs/roadmap.md`, `CHANGELOG.md`, `core/__version__.py`
- Create: `deploy/aws/terraform/read-only-scan-role.tf`, `docs/reference/exit-codes.md` (add to `mkdocs.yml` nav)
- Test: `tests/test_packaging.py` (existing; must still pass), a new docs-consistency test `tests/test_docs_consistency.py`

- [ ] **Step 1: Write `tests/test_docs_consistency.py`:** every action in the preflight's required list (`resource-explorer-2:Search`, `GetView`, `GetDefaultView`, `ListViews`, `ListIndexes`) appears in `docs/reference/iam-permissions.md` and in both CloudFormation templates; `core.__version__.__version__ == "0.7.0"`; `CHANGELOG.md` has a `## v0.7.0` heading; `docs/reference/exit-codes.md` mentions codes 2, 3, 4.
- [ ] **Step 2: Run, confirm failures.**
- [ ] **Step 3: Docs and templates:** add `GetDefaultView` and `ListViews` to IAM docs and templates; Terraform snippet creating a read-only scan role with the minimal policy; exit-codes page; troubleshooting entries for each preflight code (P1 to P7) with the fix text; env-vars entries for `STRICT_COVERAGE`, `ARGUS_SKIP_PREFLIGHT`; remove the "AWS template doesn't expose RESOURCE_EXPLORER_REGION" known gap from `docs/roadmap.md` once Task 6 exposes it.
- [ ] **Step 4: Version and changelog:** `0.7.0`; changelog entry listing behaviour changes first (empty result now fails with exit 3, preflight can fail a scan with exit 4, `--lookback-days` is now actually applied), then added fields (schema 1.1.0).
- [ ] **Step 5: Run** `pytest -q && ruff check . && black --check .`. Expected: clean.
- [ ] **Step 6: Commit** `docs: IAM, exit codes, troubleshooting; release 0.7.0 changelog`.

---

### Task 8: Release gate (live verification, then release)

Not automated; one person with a small AWS account runs this. Do not tag until every item passes.

- [ ] **Step 1: Re-run the full offline suite** on the release branch: `pytest -q`, `ruff check .`, `black --check .`. Confirm `tests/core/test_trust_regressions.py` passes.
- [ ] **Step 2: Broken-setup runs** against a test account, one scan each, recording the CLI output and exit code:
  1. Only a LOCAL Resource Explorer index: exit 4, message names the aggregator region and fix.
  2. Default view without the `tags` property: scan runs, report `preflight` shows `P6_VIEW_TAGS` warn, CLI prints it.
  3. Index still populating: warn recorded.
  4. Role without `resource-explorer-2:Search`: exit 4 listing the four actions.
  5. Admin role: `P1_IDENTITY` warn recorded.
- [ ] **Step 3: Truncation run:** `--max-resources` below the resource count with Cost Explorer resource data unavailable. Expect: `coverage.selection == "stratified_by_type"`, every discovered type present in `coverage.types`, HTML header shows "Analysed X of Y", CLI prints the same.
- [ ] **Step 4: Window run:** `--lookback-days 14`. Expect: `scan_window.metrics_lookback_days == 14`, no "90-day" wording in any finding, confidence at most `"medium"`.
- [ ] **Step 5: Variance check:** run the same scan 3 times with `--max-resources` below the resource count. Expect: identical `coverage.types` and candidate resource ids each time. Record the findings counts; large differences are logged as a known limitation, not hidden.
- [ ] **Step 6: Empty-result check:** with a provider stub or recorded session that returns `end_turn` without submitting, expect exit 3 and no report claiming success.
- [ ] **Step 7: Release:** merge to `main`, tag `v0.7.0`, let the existing release workflow (live-test gate before PyPI) run, verify `pip install argus-cloud-optimizer==0.7.0` in a clean venv runs `argus --version` and a `--dry-run` scan.
- [ ] **Step 8: Ask the original user to re-run on their account** and compare against the 11 items in `HANDOFF_user_feedback.md`.

---

## Self-review notes

- Spec coverage: #1 Task 3, #2 Task 2, #3 Task 4 (found the root cause: window forced by prompt/schema, now overridden), #4 Task 1, #5 Task 5, #6/#7/#11 Task 6, IAM/exit codes/docs Task 7, live gate Task 8. #8, #9, #10 and the deterministic baseline are out of this plan by design (should-ship/next).
- Deviation from the design: preflight is AWS-only in this release (GCP/Azure get coverage, window and no-data fixes). Recorded in design section 13.
- Types used across tasks: `Coverage`, `ScanMeta`, `PreflightResult`, `select_candidates`, `MetricSummary.status`, `ResourceFinding.confidence`/`cost_basis`, exit constants. Names match between producing and consuming tasks.
- Task order matters: 1 before 6 (error types), 2 before 3 (selection rule), 3 before 6 (`ScanMeta`), 4 before 5 (window used in confidence cap).
