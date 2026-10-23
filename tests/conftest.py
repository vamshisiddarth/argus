from __future__ import annotations

import pytest

from core.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the pydantic-settings singleton before and after every test."""
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture(autouse=True)
def _reports_go_to_tmp(tmp_path, monkeypatch):
    """Tests must not write reports into the repo's local_reports/ directory."""
    monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path / "local_reports"))
    monkeypatch.setenv("ARGUS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
