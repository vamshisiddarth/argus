"""The labelled list of test resources: what is waste, what is a look-alike decoy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KINDS = ("waste", "decoy")


class ManifestError(ValueError):
    """The manifest is malformed."""


def load_manifest(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Load and validate a manifest from a path or an already-parsed dict."""
    if isinstance(source, dict):
        data = source
    else:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    _validate(data)
    return data


def filter_manifest(manifest: dict[str, Any], exclude: set[str]) -> dict[str, Any]:
    """A copy without the given classes, for scoring a partial deployment."""
    unknown = exclude - set(manifest["classes"])
    if unknown:
        raise ManifestError(f"unknown class {sorted(unknown)[0]!r}")
    return {
        **manifest,
        "classes": {k: v for k, v in manifest["classes"].items() if k not in exclude},
        "resources": [r for r in manifest["resources"] if r["class"] not in exclude],
    }


def _validate(data: dict[str, Any]) -> None:
    if data.get("version") != 1:
        raise ManifestError("manifest version must be 1")
    tag_key = data.get("tag_key")
    if not isinstance(tag_key, str) or not tag_key:
        raise ManifestError("manifest needs a non-empty tag_key")
    classes = data.get("classes")
    if not isinstance(classes, dict) or not classes:
        raise ManifestError("manifest needs at least one class")
    for name, spec in classes.items():
        target = spec.get("target_recall")
        if not isinstance(target, (int, float)) or not 0 <= target <= 1:
            raise ManifestError(f"class {name}: target_recall must be 0 to 1")
        if not isinstance(spec.get("resource_type"), str):
            raise ManifestError(f"class {name}: resource_type is required")
    seen: set[str] = set()
    for res in data.get("resources") or []:
        rid = res.get("id")
        if not isinstance(rid, str) or not rid:
            raise ManifestError("every resource needs an id")
        if rid in seen:
            raise ManifestError(f"duplicate resource id {rid}")
        seen.add(rid)
        if res.get("class") not in classes:
            raise ManifestError(f"{rid}: unknown class {res.get('class')!r}")
        if res.get("kind") not in KINDS:
            raise ManifestError(f"{rid}: kind must be one of {KINDS}")
        expected = res.get("expected_monthly_usd")
        if expected is not None and (
            not isinstance(expected, (int, float)) or expected < 0
        ):
            raise ManifestError(f"{rid}: expected_monthly_usd cannot be negative")
