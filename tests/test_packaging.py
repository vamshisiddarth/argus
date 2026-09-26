"""
Packaging guard: every top-level package the app imports must ship in the wheel.

v0.6.0 shipped without ``integrations/`` because ``[tool.setuptools.packages.find]``
listed packages by hand. ``argus scan`` imports it after every scan, so pip users
crashed with ModuleNotFoundError before notifications went out.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOT_SHIPPED = {"tests"}


def _find_include() -> list[str]:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return list(cfg["tool"]["setuptools"]["packages"]["find"]["include"])


def _top_level_packages() -> set[str]:
    return {
        p.name
        for p in ROOT.iterdir()
        if p.is_dir() and (p / "__init__.py").exists() and p.name not in NOT_SHIPPED
    }


def test_every_top_level_package_is_packaged() -> None:
    include = _find_include()
    missing = sorted(
        pkg
        for pkg in _top_level_packages()
        if not any(fnmatch.fnmatch(pkg, pat) for pat in include)
    )
    assert not missing, (
        f"Top-level packages not in [tool.setuptools.packages.find].include: "
        f"{missing}. They would be missing from the PyPI wheel."
    )


def test_integrations_is_packaged() -> None:
    include = _find_include()
    assert any(fnmatch.fnmatch("integrations", pat) for pat in include)
    assert any(fnmatch.fnmatch("integrations.jira", pat) for pat in include)
