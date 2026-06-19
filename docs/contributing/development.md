# Development Setup

## Prerequisites

- Python 3.13+
- git

## Install

```bash
git clone https://github.com/vamshisiddarth/argus.git
cd argus
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pre-commit install
```

## Running tests

All tests run offline — no cloud credentials needed:

```bash
pytest tests/ -v
```

Subsets:

```bash
pytest tests/adapters/aws/ -v     # AWS adapter
pytest tests/adapters/gcp/ -v     # GCP adapter
pytest tests/adapters/azure/ -v   # Azure adapter
pytest tests/ai/ -v               # AI providers
pytest tests/core/ -v             # Agent loop and report generation
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
mypy .            # type check
```

Rules:
- Line length: **88 characters**
- Type hints on all public functions
- No bare `except Exception`
- Python 3.13+ syntax (`match`, `|` union types, etc.)

## Running the docs site locally

```bash
pip install mkdocs-material mkdocs-minify-plugin
mkdocs serve
```

Open [http://localhost:8000](http://localhost:8000).

## Project layout

```
argus/
├── core/               # Pure Python — no cloud imports
│   ├── agent/          # ReAct loop + system prompt + tool schemas
│   ├── models/         # ResourceFinding dataclass
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
├── entrypoints/
│   ├── cli.py
│   ├── aws_lambda.py
│   ├── gcp_cloudrun.py
│   └── azure_function.py
├── deploy/
│   ├── aws/            # CloudFormation
│   ├── gcp/            # deploy.sh
│   └── azure/          # Bicep
├── tests/              # mirrors source layout
└── docs/               # this documentation
```
