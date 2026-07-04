from __future__ import annotations

import logging
from pathlib import Path

import yaml

from core.registry import get_registry
from core.remediation.models import (
    Condition,
    MetricCondition,
    Policy,
    ScopeFilter,
)

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset(
    {
        "delete",
        "resize",
        "stop",
        "snapshot_delete",
        "reduce_replicas",
        "reduce_nodes",
        "archive",
        "convert_spot",
    }
)

_SUPPORTED_VERSIONS = frozenset({"1"})


def load_policies(policies_dir: str | Path) -> list[Policy]:
    """
    Glob-read all *.yaml files from policies_dir and parse into Policy objects.

    Raises LoadError if any file has schema errors.
    Returns [] if the directory does not exist or contains no yaml files.
    """
    path = Path(policies_dir)
    if not path.exists():
        logger.debug("policies_dir_not_found path=%s", str(path))
        return []

    files = sorted(path.glob("**/*.yaml"))
    if not files:
        logger.debug("no_policy_files_found path=%s", str(path))
        return []

    policies: list[Policy] = []
    errors: list[str] = []

    for file in files:
        try:
            file_policies = _parse_file(file)
            policies.extend(file_policies)
        except PolicyLoadError as exc:
            errors.append(str(exc))

    if errors:
        raise PolicyLoadError(
            f"{len(errors)} policy file(s) failed to load:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )

    logger.info("policies_loaded count=%d", len(policies))
    return policies


def _parse_file(path: Path) -> list[Policy]:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise PolicyLoadError(f"{path.name}: invalid YAML — {exc}") from exc

    if not isinstance(raw, dict):
        raise PolicyLoadError(f"{path.name}: must be a YAML mapping at top level")

    version = str(raw.get("version", ""))
    if version not in _SUPPORTED_VERSIONS:
        raise PolicyLoadError(
            f"{path.name}: unsupported version '{version}'. "
            f"Supported: {sorted(_SUPPORTED_VERSIONS)}"
        )

    # Each file is a single policy document
    return [_parse_policy(raw, source_file=str(path))]


def _parse_policy(raw: dict, source_file: str) -> Policy:
    fname = Path(source_file).name

    def _require(key: str) -> object:
        val = raw.get(key)
        if val is None:
            raise PolicyLoadError(f"{fname}: missing required field '{key}'")
        return val

    policy_id = str(_require("policy_id")).strip()
    name = str(_require("name")).strip()
    resource_type = str(_require("resource_type")).strip()
    action = str(_require("action")).strip()

    if not policy_id:
        raise PolicyLoadError(f"{fname}: 'policy_id' must not be empty")
    if not name:
        raise PolicyLoadError(f"{fname}: 'name' must not be empty")
    if not resource_type:
        raise PolicyLoadError(f"{fname}: 'resource_type' must not be empty")

    if action not in _VALID_ACTIONS:
        raise PolicyLoadError(
            f"{fname}: invalid action '{action}'. "
            f"Must be one of: {sorted(_VALID_ACTIONS)}"
        )

    # Warn (don't error) if resource_type not in registry — Tier 2 unavailable
    registry = get_registry()
    if resource_type != "*" and registry.get(resource_type) is None:
        logger.warning(
            "policy_unknown_resource_type policy_id=%s resource_type=%s file=%s "
            "— Tier 2 metric conditions unavailable for unknown resource types",
            policy_id,
            resource_type,
            source_file,
        )

    weight_raw = raw.get("weight", 0)
    try:
        weight = int(weight_raw)
    except (TypeError, ValueError) as err:
        raise PolicyLoadError(
            f"{fname}: 'weight' must be an integer, got {weight_raw!r}"
        ) from err

    conditions = _parse_conditions(raw.get("conditions") or {}, fname)
    include = _parse_scope(raw.get("include") or {}, fname, "include")
    exclude = _parse_scope(raw.get("exclude") or {}, fname, "exclude")
    approvers = _parse_approvers(raw.get("approvers") or [], fname)

    return Policy(
        policy_id=policy_id,
        name=name,
        resource_type=resource_type,
        conditions=conditions,
        action=action,
        approvers=approvers,
        weight=weight,
        include=include,
        exclude=exclude,
        source_file=source_file,
    )


def _parse_conditions(raw: dict, fname: str) -> Condition:
    min_cost = raw.get("min_estimated_monthly_cost_usd")
    if min_cost is not None:
        try:
            min_cost = float(min_cost)
        except (TypeError, ValueError) as err:
            raise PolicyLoadError(
                f"{fname}: 'conditions.min_estimated_monthly_cost_usd' must be a number"
            ) from err

    idle_days = raw.get("idle_days_min")
    if idle_days is not None:
        try:
            idle_days = int(idle_days)
        except (TypeError, ValueError) as err:
            raise PolicyLoadError(
                f"{fname}: 'conditions.idle_days_min' must be an integer"
            ) from err

    ai_priority_raw = raw.get("ai_priority")
    ai_priority: tuple[str, ...] | None = None
    if ai_priority_raw is not None:
        if not isinstance(ai_priority_raw, list):
            raise PolicyLoadError(f"{fname}: 'conditions.ai_priority' must be a list")
        ai_priority = tuple(str(p).lower() for p in ai_priority_raw)

    metrics = _parse_metric_conditions(raw.get("metrics") or [], fname)

    try:
        return Condition(
            min_estimated_monthly_cost_usd=min_cost,
            ai_priority=ai_priority,
            idle_days_min=idle_days,
            metrics=metrics,
        )
    except ValueError as exc:
        raise PolicyLoadError(f"{fname}: invalid condition — {exc}") from exc


def _parse_metric_conditions(raw: list, fname: str) -> tuple[MetricCondition, ...]:
    if not isinstance(raw, list):
        raise PolicyLoadError(
            f"{fname}: 'conditions.metrics' must be a list of "
            f"{{metric, operator, threshold}} objects"
        )
    result: list[MetricCondition] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PolicyLoadError(
                f"{fname}: 'conditions.metrics[{i}]' must be a mapping"
            )
        for key in ("metric", "operator", "threshold"):
            if key not in item:
                raise PolicyLoadError(
                    f"{fname}: 'conditions.metrics[{i}]' missing required key '{key}'"
                )
        try:
            result.append(
                MetricCondition(
                    metric=str(item["metric"]).strip(),
                    operator=str(item["operator"]).strip(),
                    threshold=float(item["threshold"]),
                )
            )
        except ValueError as exc:
            raise PolicyLoadError(
                f"{fname}: 'conditions.metrics[{i}]' — {exc}"
            ) from exc
    return tuple(result)


def _parse_scope(raw: dict, fname: str, field_name: str) -> ScopeFilter:
    def _to_str_tuple(key: str) -> tuple[str, ...] | None:
        val = raw.get(key)
        if val is None:
            return None
        if not isinstance(val, list):
            raise PolicyLoadError(f"{fname}: '{field_name}.{key}' must be a list")
        return tuple(str(v).strip() for v in val)

    cloud_platforms = _to_str_tuple("cloud_platforms")
    accounts = _to_str_tuple("accounts")
    regions = _to_str_tuple("regions")

    tags_raw = raw.get("tags") or []
    if not isinstance(tags_raw, list):
        raise PolicyLoadError(
            f"{fname}: '{field_name}.tags' must be a list of single-key mappings"
        )
    tags: list[dict[str, list[str]]] = []
    for i, item in enumerate(tags_raw):
        if not isinstance(item, dict) or len(item) != 1:
            raise PolicyLoadError(
                f"{fname}: '{field_name}.tags[{i}]' must be a single-key mapping "
                f"e.g. '- environment: [prod, staging]'"
            )
        key, vals = next(iter(item.items()))
        if not isinstance(vals, list):
            raise PolicyLoadError(
                f"{fname}: '{field_name}.tags[{i}].{key}' must be a list of values"
            )
        tags.append({str(key): [str(v) for v in vals]})

    return ScopeFilter(
        cloud_platforms=cloud_platforms,
        accounts=accounts,
        regions=regions,
        tags=tuple(tags),
    )


def _parse_approvers(raw: list, fname: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise PolicyLoadError(
            f"{fname}: 'approvers' must be a list of strings "
            f'(group names or emails), e.g. ["platform-team", "j@co.com"]'
        )
    result: list[str] = []
    for i, item in enumerate(raw):
        s = str(item).strip()
        if not s:
            raise PolicyLoadError(
                f"{fname}: 'approvers[{i}]' must not be empty"
            )
        result.append(s)
    return tuple(result)


class PolicyLoadError(Exception):
    """Raised when a policy file fails schema validation."""
