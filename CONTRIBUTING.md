# Contributing to Argus

Thanks for your interest in contributing. This document explains how to set up a development environment, run the tests, and add new cloud adapters or AI providers.

---

## Table of contents

- [Development setup](#development-setup)
- [Running tests](#running-tests)
- [Code style](#code-style)
- [Adding a new cloud adapter](#adding-a-new-cloud-adapter)
- [Adding a new resource type to the registry](#adding-a-new-resource-type-to-the-registry)
- [Adding a new AI provider](#adding-a-new-ai-provider)
- [Adding a remediation policy](#adding-a-remediation-policy)
- [Submitting a pull request](#submitting-a-pull-request)

---

## Development setup

```bash
git clone https://github.com/vamshisiddarth/argus.git
cd argus

python3.11 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

Copy the environment file and fill in the minimum values for local testing:

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY and DRY_RUN=true at minimum
```

---

## Running tests

All tests run offline — no real cloud credentials needed:

```bash
pytest tests/ -v        # 1458 tests across core, adapters, ai, and entrypoints
```

To run a subset:

```bash
pytest tests/adapters/aws/ -v        # AWS adapter only
pytest tests/core/ -v                # Core agent logic + chat session
pytest tests/ai/ -v                  # AI providers only
```

With coverage:

```bash
pytest tests/ --cov=. --cov-report=term-missing
```

**Important**: never use real cloud credentials in tests. Use `unittest.mock` to mock all SDK calls. See `tests/adapters/aws/test_cloudwatch.py` for a complete example.

---

## Code style

We use **Ruff** for both formatting and linting:

```bash
ruff format .
ruff check . --fix
```

Rules:
- Line length: **88 characters** (Black default)
- **Type hints on all public functions** — no exceptions
- **No bare `except Exception`** — catch typed SDK exceptions
- **Python 3.11+** minimum — use `match/case` and `X | Y` union types freely; avoid `type` statement (3.12+ only)
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

Add `"mycloud"` to the `--cloud` choices and import your adapter in `_build_adapter()`.

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

## Adding a new resource type to the registry

The **Resource Registry** (`core/registry/`) is the single source of truth for every resource type Argus knows about. Adding a new type here automatically makes it available in AI prompts, the HTML report filter, the Slack digest, and the chat formatter — no other files need changing.

### Where to add it

| Cloud | File |
|-------|------|
| AWS   | `core/registry/aws.py` |
| GCP   | `core/registry/gcp.py` |
| Azure | `core/registry/azure.py` |

### Example — adding an AWS transfer family server

```python
# core/registry/aws.py
ResourceTypeSpec(
    type_id="AWS::Transfer::Server",       # must match the Resource Explorer type string
    cloud="aws",
    display_name="Transfer Family Server", # shown in Slack, HTML report, and chat
    service="Storage",                     # groups this type in the REMEDIATION ACTIONS prompt section
    metrics=(
        _M("FilesIn",   "AWS/Transfer", "Sum", "ServerId"),
        _M("FilesOut",  "AWS/Transfer", "Sum", "ServerId"),
        _M("BytesIn",   "AWS/Transfer", "Sum", "ServerId"),
    ),
    actions=("delete", "stop", "resize"),  # verbs from _VALID_ACTIONS in registry.py
    # delete — wipe the server entirely
    # stop   — stop the server; storage still billed, useful for dev servers
    # resize — downgrade to a smaller instance type
    typical_monthly_cost_usd=30.0,        # rough on-demand estimate; used for cost filtering
    docs_url="https://docs.aws.amazon.com/transfer/latest/userguide/",
),
```

### Valid action verbs

Only verbs in `_VALID_ACTIONS` (defined in `core/registry/registry.py`) are accepted:

| Verb | Meaning |
|------|---------|
| `delete` | Permanently remove the resource |
| `stop` | Stop/pause without deleting (still incurs storage cost) |
| `resize` | Change instance type or tier |
| `snapshot_delete` | Delete orphaned snapshots/backups |
| `reduce_replicas` | Lower read-replica count |
| `reduce_nodes` | Shrink cluster node count |
| `archive` | Move data to cheaper storage tier |
| `convert_spot` | Replace on-demand with Spot/Preemptible |

### Adding CLI command templates (optional)

If you also want concrete remediation commands, add an entry to `core/remediation/__init__.py`:

```python
"AWS::Transfer::Server": {
    "stop":   "aws transfer stop-server --server-id {resource_id} --region {region}",
    "delete": "aws transfer delete-server --server-id {resource_id} --region {region}",
},
```

Actions listed here must be a subset of the spec's `actions` tuple — the integration tests will catch any mismatch.

### Tests

Run the integration suite to verify your entry passes all data-quality checks:

```bash
pytest tests/core/test_registry_integration.py -v
```

The parametrized suite checks every spec for: valid cloud field, non-empty display name, at least one metric, valid action vocab, and a positive `typical_monthly_cost_usd`.

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

Add the new provider to the `AI_PROVIDER` env var handling in `entrypoints/cli.py` (`_build_ai_provider()` in `entrypoints/cli_chat.py` for chat mode).

### 4. Write tests

Create `tests/ai/test_myprovider.py`. Mock all HTTP calls — no real API calls in tests. See `tests/ai/test_anthropic.py` for a reference.

---

## Adding a remediation policy

Policies live in `config/policies/`. Each file is a single YAML document that
tells the engine which findings to act on and what action to propose.

### Minimal example

```yaml
version: "1"

policy_id: my-new-policy          # must be unique across all files
name: Human-readable name
resource_type: AWS::RDS::DBInstance  # or "*" for all types
action: resize                    # must be valid for this resource type
weight: 10                        # higher = evaluated first (first match wins)

conditions:                       # ALL conditions must be true
  ai_priority: [high, medium]     # Tier 1 — universal
  min_estimated_monthly_cost_usd: 50
  idle_days_min: 14
  metrics:                        # Tier 2 — registry-known types only
    - metric: CPUUtilization
      operator: lt
      threshold: 5.0

exclude:
  tags:
    - environment: [prod, production]   # never touch production
    - argus-exempt: ["true"]            # opt-out tag
```

### Step-by-step

1. **Pick a resource type.** Run `argus policies docs` to see all types, their
   valid metrics, and valid actions. Using an action that isn't registered for
   the type will fail at load time.

2. **Write the policy file** in `config/policies/`. File name should match
   `policy_id` (kebab-case + `.yaml`).

3. **Validate it:**
   ```
   argus policies validate --dir config/policies
   ```
   Fix any errors before proceeding. Common mistakes: wrong action for type,
   duplicate policy_id, conflicting weights with overlapping scope.

4. **Dry-run against a real scan report:**
   ```
   argus policies plan --dir config/policies --report local_reports/latest.json
   ```
   Confirm the right findings match and no unintended resources are included.

5. **Add a test** in `tests/core/remediation/test_loader.py` or
   `test_validator.py` if your policy exercises a new condition combination.

### Rules

- **Never remove the `exclude: tags: argus-exempt: ["true"]` guard.** It lets
  teams opt individual resources out without changing the policy.
- **Always exclude production** unless the policy has human-review gating
  (i.e., an apply workflow that requires Jira ticket approval).
- **Weight reflects confidence, not priority.** A weight-20 policy fires
  instead of weight-10 for the same resource — use higher weights for
  narrower, more specific policies.

---

## Submitting a pull request

1. Fork the repo and create a branch: `git checkout -b feat/my-feature`
2. Make your changes
3. Run the full test suite: `pytest tests/ -v` — all tests must pass
4. Run the linter: `ruff format . && ruff check .`
5. Open a PR against `main`

**PR checklist:**
- [ ] All existing tests pass
- [ ] New code has tests (aim for the same coverage level as existing adapters)
- [ ] Type hints on all public functions
- [ ] No real cloud credentials or API keys in any file
- [ ] `CLAUDE.md` updated if you added a new adapter or changed the architecture
