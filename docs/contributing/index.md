# Contributing

Thanks for your interest in contributing to Argus!

- :material-laptop: [Development Setup](development.md) — local environment, running tests, code style
- :material-cloud-plus: [Adding a Cloud Adapter](new-adapter.md) — how to add a new cloud (IBM Cloud, OCI, etc.)
- :material-robot-excited: [Adding an AI Provider](new-ai-provider.md) — how to add a new model or provider
- :material-rocket-launch-outline: [Releasing](releasing.md) — design → plan → build → test → release candidate → live test → publish

## Quick contribution guide

1. Fork the repo and create a branch
2. Make your changes
3. Run `pytest tests/ -v` — all tests must pass
4. Run `ruff format . && ruff check .` (CI checks both)
5. Open a PR against `main`

## PR checklist

- [ ] All existing tests pass (`pytest tests/ -v`)
- [ ] New code has tests
- [ ] Type hints on all public functions
- [ ] No real cloud credentials or API keys in any file
- [ ] `ARCHITECTURE.md` and the relevant `docs/` pages updated if behavior or architecture changed
