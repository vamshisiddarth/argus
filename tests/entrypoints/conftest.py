"""
Shared fixtures for entrypoint tests.

validate_environment() now runs at handler startup and requires SLACK_WEBHOOK_URL
(unless DRY_RUN=true). Tests that exercise handler logic but don't care about
Slack delivery get DRY_RUN=true injected automatically via this autouse fixture.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _dry_run_by_default(monkeypatch):
    """Set DRY_RUN=true for every entrypoint test unless already set."""
    monkeypatch.setenv("DRY_RUN", "true")
