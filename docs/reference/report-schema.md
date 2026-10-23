# Report JSON Schema

Version: **1.1.0**

Every Argus scan produces a JSON report with the following top-level fields.

## Top-level fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `string` | Schema version identifier. Currently `"1.1.0"`. |
| `scan_id` | `string` | UUID v4 unique to this scan. |
| `generated_at` | `string` | ISO 8601 timestamp (UTC) when the report was generated. |
| `cloud` | `string` | Cloud provider: `"aws"`, `"gcp"`, or `"azure"`. |
| `accounts_scanned` | `string[]` | List of account/project/subscription IDs scanned. |
| `total_estimated_waste_usd` | `number` | Sum of all findings' `estimated_monthly_cost`, rounded to 2 decimal places. |
| `findings_count` | `integer` | Number of findings in this report. |
| `findings` | `Finding[]` | Array of finding objects, sorted by `estimated_monthly_cost` descending. |
| `executive_summary` | `string` | AI-generated 3–5 sentence summary for non-technical stakeholders. |
| `agent_input_tokens` | `integer` | Total input tokens consumed by the AI agent during this scan. |
| `agent_output_tokens` | `integer` | Total output tokens consumed by the AI agent during this scan. |
| `estimated_agent_cost_usd` | `number` | Estimated AI cost for this scan in USD. |
| `scan_diff` | `ScanDiff` | Cross-scan comparison data. On the first scan (no previous report found), `previous_scan_id` is `null` and every finding counts as new. |
| `scan_errors` | `object[]` | Accounts/projects/subscriptions that failed to scan: `{account_id, account_name, error}`. Empty when all succeeded. |
| `skipped_resource_types` | `string[]` | Resource types that were skipped during the scan (for example, GCP asset types whose API isn't enabled). |
| `registry_warnings` | `string[]` | Invalid resource-registry entries skipped at load time. Normally empty. |
| `coverage` | `Coverage \| null` | What the scan actually analysed. See [Coverage object](#coverage-object). `null` when the entrypoint could not provide it. Added in 1.1.0. |
| `scan_window` | `object \| null` | Settings actually used: `metrics_lookback_days`, `cost_lookback_days` (the effective cost window, at most 14 on AWS), `activity_lookback_days`, `cost_basis`, `max_resources` and `max_resources_source` (`explicit` or `budget`). Added in 1.1.0. |
| `preflight` | `object \| null` | Results of the pre-scan environment checks. Added in 1.1.0. |
| `waste_by_confidence` | `object` | `total_estimated_waste_usd` split into `high`, `medium`, `low` and `unrated` (findings with no confidence). Added in 1.1.0. |
| `total_is_estimate` | `boolean` | `true` unless every finding's `cost_basis` is `billed`; headlines then say the total is not billed. Added in 1.1.0. |

## Coverage object

| Field | Type | Description |
|---|---|---|
| `discovered` | `integer` | Billable resources found after exclusion filters. |
| `analysed` | `integer` | Resources handed to the AI. |
| `dropped` | `integer` | `discovered - analysed`. |
| `truncated` | `boolean` | `true` when `dropped > 0` (the `MAX_RESOURCES_PER_SCAN` cap bit). |
| `selection` | `string` | `"cost_desc"` (cost data available), `"stratified_by_type"` (round-robin across types) or `"mixed"` (multi-account). |
| `cost_data_available` | `boolean` | Whether any per-resource cost was returned. |
| `regions_covered` | `string[]` | Regions in the discovered inventory. |
| `types` | `object` | Per resource type: `{discovered, analysed}`. |
| `discovery_complete` | `boolean \| null` | `false` when a discovery query hit the provider's result limit (AWS Resource Explorer returns at most 1,000 per query; Argus then searches region by region and sets this only if a single region still overflows). `null` when the adapter does not report it. Added in 1.1.0. |

## Finding object

| Field | Type | Description |
|---|---|---|
| `resource_id` | `string` | Cloud-native resource identifier (ARN, self-link, or resource ID). |
| `resource_type` | `string` | Registry type ID (e.g. `"AWS::EC2::Instance"`, `"sqladmin.googleapis.com/Instance"`, `"microsoft.compute/virtualmachines"`). See [Resource Types](resource-types.md). |
| `cloud` | `string` | Cloud provider. |
| `region` | `string` | Region or location where the resource exists. |
| `name` | `string \| null` | Human-readable name tag, if available. |
| `estimated_monthly_cost` | `number` | Estimated monthly cost in USD. |
| `waste_reason` | `string` | AI-written explanation of why the resource is considered idle. |
| `recommendation` | `string` | AI-written recommended action (delete, resize, tag, etc.). |
| `priority` | `string` | `"high"`, `"medium"`, or `"low"` — assigned by the AI. |
| `metrics_summary` | `object` | Key metric signals the AI used to make its decision. |
| `tags` | `object` | Resource tags as key-value pairs. |
| `confidence` | `string \| null` | `"low"`, `"medium"` or `"high"`. Forced to `low` when the metrics behind the finding were unavailable; capped at `medium` for windows under 90 days. Added in 1.1.0. |
| `cost_basis` | `string \| null` | Where the dollar figure comes from: `"billed"` (Cost Explorer), `"list_price"` (Argus price catalog, us-east-1 list prices), `"model_estimate"` (the AI's guess) or `"unknown"` (no figure). Added in 1.1.0. |
| `detected_by` | `string \| null` | `"model"` or `"rule:<id>"` for a [baseline rule](../concepts/baseline-rules.md). Added in 1.1.0. |
| `last_activity` | `string \| null` | ISO 8601 timestamp of the last detected activity, or `null`. |
| `scan_time` | `string` | ISO 8601 timestamp of when the resource was scanned. |
| `account_id` | `string \| null` | Account / project / subscription the resource belongs to. Added in 1.0.1; `null` if it couldn't be attributed. |
| `account_name` | `string \| null` | Display name for `account_id` (from `accounts.yaml` / `ACCOUNTS_CONFIG`, else the ID). Added in 1.0.1. |
| `status` | `string` | `"new"` or `"recurring"`, set by cross-scan comparison. Resolved resources aren't in `findings`; they're listed in `scan_diff.resolved_resource_ids`. |

## ScanDiff object

| Field | Type | Description |
|---|---|---|
| `previous_scan_id` | `string \| null` | Scan ID of the previous report used for comparison. |
| `new_findings` | `integer` | Count of findings not present in the previous scan. |
| `recurring_findings` | `integer` | Count of findings present in both scans. |
| `resolved_findings` | `integer` | Count of findings from the previous scan no longer present. |
| `resolved_resource_ids` | `string[]` | Resource IDs that were in the previous scan but not this one. |

## Versioning policy

The `schema_version` field uses semantic versioning:

- **Patch** (1.0.x): new optional fields added. Existing consumers are unaffected.
- **Minor** (1.x.0): new optional top-level blocks, changed field semantics, or optional fields becoming required.
- **Major** (x.0.0): fields removed or renamed. Consumers must update.

Consumers should check `schema_version` before parsing and handle unknown versions gracefully.

| Version | Change |
|---|---|
| 1.1.0 (v0.7.0) | New optional top-level `coverage`, `scan_window` and `preflight` blocks. Nothing removed or renamed. |
| 1.0.1 (v0.6.0) | Findings gained optional `account_id` and `account_name`. |
| 1.0 | Initial schema. |
