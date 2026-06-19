from __future__ import annotations

import pytest

from core.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the pydantic-settings singleton before and after every test."""
    clear_settings_cache()
    yield
    clear_settings_cache()
