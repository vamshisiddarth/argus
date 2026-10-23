# Exit Codes

`argus scan` (and the legacy `argus --run-now`) exits with one of these codes.
Orchestrators such as cron wrappers, CI jobs and Cloud Run Jobs can tell the
failure modes apart without parsing output.

| Code | Meaning | What to do |
|---|---|---|
| `0` | Scan finished and findings were submitted (possibly an explicit empty list). | Nothing. |
| `1` | Configuration or runtime error, or `--strict-coverage` / `STRICT_COVERAGE=true` and the resource cap left resources unanalysed. | Read the message on stderr. For coverage, raise `MAX_RESOURCES_PER_SCAN`. |
| `2` | The LLM budget (`--llm-budget`, default $2.00) was exceeded and the scan aborted. | Raise the budget or lower `MAX_RESOURCES_PER_SCAN`. |
| `3` | The model stopped without calling `submit_findings`, even after one reminder. The scan is treated as failed, not as "no findings". | Re-run. If it repeats, check the model/provider and the logs. |
| `4` | Preflight failed: the environment would give silently partial or empty results (for example no Resource Explorer aggregator index). No LLM budget was spent. | Follow the fix printed for each failed check, see [Troubleshooting](troubleshooting.md#preflight-checks). |

In AWS Lambda, Cloud Run and Azure Functions there is no process exit code for
every case: failures surface as an invocation error with the same message.
