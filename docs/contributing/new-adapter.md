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
        days: int = 14,
    ) -> MetricSummary:
        # Fetch usage metrics for the past N days
        # Return MetricSummary(has_data=bool, metrics={"MetricName": float_avg})
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
    The agent calls `get_cost` with a list of all candidate IDs at once.
    Never make per-resource cost API calls — they are expensive and slow.

!!! tip "Handle errors gracefully"
    - Raise `PermissionError` for auth failures (agent loop handles this)
    - Return zeros for cost/metrics on non-fatal errors (log a warning)
    - Never raise from `get_cost` or `get_metrics` — return safe defaults

## 4. Wire it up

Add the new cloud to `entrypoints/cli.py`:

```python title="entrypoints/cli.py"
parser.add_argument("--cloud", choices=["aws", "gcp", "azure", "mycloud"], ...)

# ...
if args.cloud == "mycloud":
    from adapters.mycloud.adapter import MyCloudAdapter
    adapter = MyCloudAdapter.from_env()
    loop = AgentLoop(ai_provider=ai_provider, cloud_adapter=adapter)
    findings, summary = loop.run(cloud="mycloud", ...)
```

## 5. Write tests

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

## 6. Update `CLAUDE.md`

Add the new adapter to the Build Phases section and project structure.
