# Adding a Cloud Adapter

This guide walks through adding support for a new cloud provider (e.g. IBM Cloud, Oracle Cloud, DigitalOcean).

## 1. Create the directory

```
adapters/
└── mycloud/
    ├── __init__.py
    ├── adapter.py      # implements CloudAdapter
    ├── resources.py    # list_resources
    ├── metrics.py      # get_metrics
    ├── billing.py      # get_cost
    └── activity.py     # get_last_activity
```

## 2. Implement the four methods

```python title="adapters/mycloud/adapter.py"
from __future__ import annotations

import os
from datetime import datetime

from adapters.base import CloudAdapter, MetricSummary, Resource


class MyCloudAdapter(CloudAdapter):

    def __init__(self, project_id: str) -> None:
        self._project_id = project_id

    @classmethod
    def from_env(cls) -> "MyCloudAdapter":
        project_id = os.environ.get("MYCLOUD_PROJECT_ID")
        if not project_id:
            raise EnvironmentError("MYCLOUD_PROJECT_ID is not set.")
        return cls(project_id=project_id)

    def list_resources(
        self,
        ignore_regions: list[str] | None = None,
    ) -> list[Resource]:
        # Call your cloud's resource listing API
        # Filter non-billable types before returning
        # Return list[Resource]
        ...

    def get_metrics(
        self,
        resource_id: str,
        resource_type: str,
        days: int = 90,
    ) -> MetricSummary:
        # Fetch usage metrics for the past N days (METRICS_LOOKBACK_DAYS, default 90)
        # Return MetricSummary(resource_id=..., resource_type=..., period_days=days,
        #                      metrics={"MetricName": value}, has_data=bool)
        ...

    def get_cost(
        self,
        resource_ids: list[str],
        days: int = 30,
    ) -> dict[str, float]:
        # ALWAYS batch — one API call for all resource_ids
        # Return {resource_id: monthly_usd_float}
        ...

    def get_last_activity(
        self,
        resource_id: str,
        resource_type: str,
    ) -> datetime | None:
        # Return the last meaningful activity timestamp
        # Return None if no activity found
        ...
```

## 3. Key rules

!!! warning "Never hardcode idle thresholds"
    Return raw data — averages, counts, timestamps.
    Let the AI decide what counts as idle.

!!! warning "Always batch `get_cost`"
    Phase 0 calls `get_cost` once with **every** discovered resource ID, before the AI runs.
    Never make per-resource cost API calls — they are expensive and slow.

!!! warning "Read-only only"
    The adapter contract has four read methods. CI scans adapter method names for mutating
    keywords, and the agent loop only allows its five read-only tools.

!!! tip "Handle errors gracefully"
    - An exception from `list_resources` aborts the scan for that account/project
    - If `get_cost` raises in Phase 0, the scan continues with no cost data (all resources $0)
    - An exception from `get_metrics` / `get_last_activity` is returned to the AI as a tool error
    - Prefer logging a warning and returning safe defaults (zero cost, `has_data=False`, `None`) for non-fatal errors

## 4. Register its resource types

Add a `core/registry/mycloud.py` listing a `ResourceTypeSpec` per type (display name, metrics,
valid remediation actions), and load it in `core/registry/factory.py`. The agent prompt, reports,
`argus policies docs`, and the policy validator all read from the registry.

## 5. Wire it up

The CLI doesn't build adapters itself; `argus scan --cloud <x>` dispatches to the runtime entrypoint
for that cloud (`entrypoints/aws_lambda.py`, `gcp_cloudrun.py`, `azure_function.py`). For a new cloud:

1. Create `entrypoints/mycloud_<runtime>.py` that builds the AI provider and adapter and runs the loop:

    ```python
    from core.agent.loop import AgentLoop

    adapter = MyCloudAdapter.from_env()
    loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
    findings, summary = loop.run(cloud="mycloud", ignore_regions=ignore_regions, accounts=accounts)
    ```

    Follow an existing entrypoint for the rest: `resolve_secrets()`, `validate_environment()`,
    `compare_scans()`, `build_report()`, report storage, `run_remediation()`, and `notify_all()`.

2. Add `"mycloud"` to the `--cloud` choices and to `_run_scan()` in `entrypoints/cli.py`.

## 6. Write tests

Create `tests/adapters/mycloud/` with `unittest.mock` tests.
Never make real cloud calls in tests.

```python title="tests/adapters/mycloud/test_resources.py"
from unittest.mock import MagicMock, patch
from adapters.mycloud.resources import list_resources

def test_returns_billable_resources():
    with patch("adapters.mycloud.resources.MyCloudSDK") as mock_sdk:
        mock_sdk.return_value.list.return_value = [...]
        result = list_resources(project_id="test-project")
    assert len(result) == 2
    assert all(r.cloud == "mycloud" for r in result)
```

Aim for the same coverage level as the AWS/GCP/Azure adapters (~8-10 tests per module).

## 7. Update the docs

Add the new cloud to `ARCHITECTURE.md`, `docs/concepts/adapters.md`, `docs/reference/resource-types.md`,
`docs/reference/iam-permissions.md`, and `docs/roadmap.md`.
