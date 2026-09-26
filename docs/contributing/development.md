# Development Setup

## Prerequisites

- Python 3.11+
- git

## Install

```bash
git clone https://github.com/vamshisiddarth/argus.git
cd argus
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install pre-commit    # not included in the dev extra
pre-commit install
```

## Running tests

All tests run offline — no cloud credentials needed:

```bash
pytest tests/ -v                   # unit tests (integration tests are excluded by default)
make test-integration              # integration tests only (pytest -m integration)
make test-all                      # everything
```

Subsets:

```bash
pytest tests/adapters/aws/ -v     # AWS adapter
pytest tests/adapters/gcp/ -v     # GCP adapter
pytest tests/adapters/azure/ -v   # Azure adapter
pytest tests/ai/ -v               # AI providers
pytest tests/core/ -v             # Agent loop, chat session, report generation, remediation engine
pytest tests/integrations/ -v     # Jira tracker
pytest tests/entrypoints/ -v      # CLI and runtime entrypoints
```

With coverage:

```bash
pytest tests/ --cov=. --cov-report=term-missing
```

## Code style

Pre-commit hooks run **ruff** (lint + format) and **mypy** automatically on each commit.
To set them up:

```bash
pre-commit install          # one-time setup
pre-commit run --all-files  # manual run on all files
```

You can also run the tools directly:

```bash
ruff format .     # format
ruff check .      # lint
ruff check --fix  # auto-fix lint issues
mypy core/ adapters/ ai/ entrypoints/ --ignore-missing-imports --no-warn-unused-ignores   # same as CI
```

Rules:
- Line length: **88 characters**
- Type hints on all public functions
- No bare `except Exception`, except in top-level runners that must never block delivery (marked `# noqa: BLE001`)

CI runs `ruff format --check .`, `ruff check .`, mypy, the test suite on Python 3.11–3.13, and a strict docs build.
Note that the Makefile's `lint` / `fmt` targets still call `black`; CI uses `ruff format`, so prefer the commands above.
- Python 3.11+ minimum (`match`, `|` union types freely; avoid 3.12+ `type` statement)

## Running the docs site locally

```bash
pip install mkdocs-material mkdocs-minify-plugin mike   # already included in the dev extra
mkdocs serve
```

Open [http://localhost:8000](http://localhost:8000).

## Project layout

```
argus/
├── core/               # Pure Python — no cloud imports
│   ├── agent/          # ReAct loop, chat session, system prompt + tool schemas
│   ├── models/         # ResourceFinding dataclass
│   ├── registry/       # Resource-type registry (114 types) — metrics, actions, display names
│   ├── remediation/    # Policy loader, validator, engine, audit log, rightsizing
│   └── reports/        # Report builder, multi-cloud merge, export, notifications
├── adapters/
│   ├── base.py         # CloudAdapter abstract class
│   ├── aws/            # AWS adapter
│   ├── gcp/            # GCP adapter
│   └── azure/          # Azure adapter
├── ai/
│   ├── base.py         # AIProvider abstract class
│   ├── anthropic.py    # Anthropic direct API
│   ├── bedrock.py      # AWS Bedrock
│   ├── vertexai.py     # Vertex AI (Gemini)
│   └── azure_openai.py # Azure OpenAI (GPT-4o)
├── integrations/
│   ├── base.py         # ChangeTracker abstract class
│   └── jira/           # Jira client, ADF formatter, tracker (dedup + diff)
├── entrypoints/
│   ├── cli.py          # argus scan / chat / policies subcommands
│   ├── _remediation.py # post-scan remediation runner (opt-in)
│   ├── cli_chat.py     # interactive chat REPL
│   ├── aws_lambda.py
│   ├── gcp_cloudrun.py
│   └── azure_function.py
├── config/
│   ├── policies/       # 13 bundled remediation policies
│   ├── policies.example/
│   └── integrations.yaml.example
├── deploy/
│   ├── aws/            # CloudFormation / SAM
│   ├── gcp/            # deploy.sh
│   └── azure/          # Bicep
├── examples/
│   └── chat_demo.py    # demo script for chat mode (no API key needed)
├── tests/              # mirrors source layout
└── docs/               # this documentation
```
