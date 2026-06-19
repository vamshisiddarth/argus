# Report JSON Schema

Version: **1.0**

Every Argus scan produces a JSON report with the following top-level fields.

## Top-level fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `string` | Schema version identifier. Currently `"1.0"`. |
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
| `scan_diff` | `ScanDiff \| null` | Cross-scan comparison data. `null` on first scan or if no previous report found. |

## Finding object

| Field | Type | Description |
|---|---|---|
| `resource_id` | `string` | Cloud-native resource identifier (ARN, self-link, or resource ID). |
| `resource_type` | `string` | Resource type label (e.g. `"EC2"`, `"CloudSQL"`, `"VirtualMachine"`). |
| `cloud` | `string` | Cloud provider. |
| `region` | `string` | Region or location where the resource exists. |
| `name` | `string \| null` | Human-readable name tag, if available. |
| `estimated_monthly_cost` | `number` | Estimated monthly cost in USD. |
| `waste_reason` | `string` | AI-written explanation of why the resource is considered idle. |
| `recommendation` | `string` | AI-written recommended action (delete, resize, tag, etc.). |
| `priority` | `string` | `"high"`, `"medium"`, or `"low"` — assigned by the AI. |
| `metrics_summary` | `object` | Key metric signals the AI used to make its decision. |
| `tags` | `object` | Resource tags as key-value pairs. |
| `last_activity` | `string \| null` | ISO 8601 timestamp of the last detected activity, or `null`. |
| `scan_time` | `string` | ISO 8601 timestamp of when the resource was scanned. |
| `status` | `string` | `"new"`, `"recurring"`, or `"resolved"`. Set by cross-scan comparison. |

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
- **Minor** (1.x.0): field semantics changed or optional fields become required.
- **Major** (x.0.0): fields removed or renamed. Consumers must update.

Consumers should check `schema_version` before parsing and handle unknown versions gracefully.
