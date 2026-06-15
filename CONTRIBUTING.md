# Contributing to Argus

Thanks for your interest in contributing. This document explains how to set up a development environment, run the tests, and add new cloud adapters or AI providers.

---

## Table of contents

- [Development setup](#development-setup)
- [Running tests](#running-tests)
- [Code style](#code-style)
- [Adding a new cloud adapter](#adding-a-new-cloud-adapter)
- [Adding a new AI provider](#adding-a-new-ai-provider)
- [Submitting a pull request](#submitting-a-pull-request)

---

## Development setup

```bash
git clone https://github.com/vamshisiddarth/argus.git
cd argus

python3.13 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

Copy the environment file and fill in the minimum values for local testing:

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY and DRY_RUN=true at minimum
```

---

## Running tests

All 187 tests run offline — no real cloud credentials needed:

```bash
pytest tests/ -v
```

To run a subset:

```bash
pytest tests/adapters/aws/ -v        # AWS adapter only
pytest tests/core/ -v                # Core agent logic only
pytest tests/ai/ -v                  # AI providers only
```

With coverage:

```bash
pytest tests/ --cov=. --cov-report=term-missing
```

**Important**: never use real cloud credentials in tests. Use `unittest.mock` to mock all SDK calls. See `tests/adapters/aws/test_cloudwatch.py` for a complete example.

---

## Code style

We use **Black** (formatter) and **Ruff** (linter):

```bash
black .
ruff check . --fix
```

Rules:
- Line length: **88 characters** (Black default)
- **Type hints on all public functions** — no exceptions
- **No bare `except Exception`** — catch typed SDK exceptions
- **Python 3.13+** — use modern syntax freely (`match`, `|` union types, etc.)
- No `subprocess` calls to cloud CLIs — always use official SDKs

---

## Adding a new cloud adapter

All cloud adapters implement the `CloudAdapter` abstract class in `adapters/base.py`.

### 1. Create the adapter directory

```
adapters/
└── mycloud/
    ├── __init__.py
    ├── adapter.py          # implements CloudAdapter
    ├── resources.py        # list_resources — discovery
    ├── metrics.py          # get_metrics — usage signals
    ├── billing.py          # get_cost — cost data
    └── activity.py         # get_last_activity — last touched timestamp
```

### 2. Implement the four methods

```python
from adapters.base import CloudAdapter, Resource, MetricSummary
from datetime import datetime

class MyCloudAdapter(CloudAdapter):

    def list_resources(
        self,
        ignore_regions: list[str] | None = None,
    ) -> list[Resource]:
        """Return every billable resource in the account."""
        ...

    def get_metrics(
        self,
        resource_id: str,
        resource_type: str,
        days: int = 14,
    ) -> MetricSummary:
        """Return usage metrics for the past N days."""
        ...

    def get_cost(
        self,
        resource_ids: list[str],
        days: int = 30,
    ) -> dict[str, float]:
        """Return USD cost per resource. Always batch — never call per-resource."""
        ...

    def get_last_activity(
        self,
        resource_id: str,
        resource_type: str,
    ) -> datetime | None:
        """Return the timestamp of the last meaningful activity, or None."""
        ...
```

### 3. Add a `from_env()` classmethod

```python
@classmethod
def from_env(cls) -> "MyCloudAdapter":
    project = os.environ.get("MYCLOUD_PROJECT_ID")
    if not project:
        raise EnvironmentError("MYCLOUD_PROJECT_ID is not set.")
    return cls(project_id=project)
```

### 4. Wire it up in `entrypoints/cli.py`

Add `"mycloud"` to the `--cloud` choices and import your adapter there.

### 5. Write tests

Create `tests/adapters/mycloud/` with `unittest.mock` tests. Aim for coverage of:
- Happy path (resources returned correctly)
- Empty result (no resources)
- Permission errors (raise `PermissionError`)
- SDK errors (return safe defaults, log a warning)

### Key rules for adapters

- **No hardcoded idle thresholds** — return raw data; let the AI reason about idleness
- **Batch cost calls** — one API call for all resource IDs, not one per resource
- **Raise `PermissionError`** for auth failures (the agent loop handles this gracefully)
- **Return zeros** for cost/metrics on non-fatal errors (log a warning instead of raising)
- **No cloud imports in `core/`** — adapters are the only place AWS/GCP/Azure SDKs are used

---

## Adding a new AI provider

All AI providers implement the `AIProvider` abstract class in `ai/base.py`.

### 1. Create the provider file

```python
# ai/myprovider.py
from __future__ import annotations
from ai.base import AIProvider, AIResponse, Message, Tool

class MyProvider(AIProvider):

    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        # Convert to your provider's format, call the API, convert response back
        ...
```

### 2. Add a `from_env()` classmethod

```python
@classmethod
def from_env(cls) -> "MyProvider":
    api_key = os.environ.get("MYPROVIDER_API_KEY")
    if not api_key:
        raise EnvironmentError("MYPROVIDER_API_KEY is not set.")
    return cls(api_key=api_key)
```

### 3. Wire it up

Add the new provider to the `AI_PROVIDER` env var handling in `entrypoints/aws_lambda.py` (and `cli.py`).

### 4. Write tests

Create `tests/ai/test_myprovider.py`. Mock all HTTP calls — no real API calls in tests. See `tests/ai/test_anthropic.py` for a reference.

---

## Submitting a pull request

1. Fork the repo and create a branch: `git checkout -b feat/my-feature`
2. Make your changes
3. Run the full test suite: `pytest tests/ -v` — all tests must pass
4. Run the linter: `black . && ruff check .`
5. Open a PR against `main`

**PR checklist:**
- [ ] All existing tests pass
- [ ] New code has tests (aim for the same coverage level as existing adapters)
- [ ] Type hints on all public functions
- [ ] No real cloud credentials or API keys in any file
- [ ] `CLAUDE.md` updated if you added a new adapter or changed the architecture
