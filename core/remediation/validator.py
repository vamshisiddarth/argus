from __future__ import annotations

from dataclasses import dataclass

from core.remediation.models import Policy, ScopeFilter


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def validate_policies(policies: list[Policy]) -> ValidationResult:
    """
    Cross-policy validation: conflict detection, duplicate IDs, unreachable policies.

    Errors (must fix):
      - Duplicate policy_id across files
      - Same resource_type + same weight + overlapping scope (any action)

    Warnings (should fix):
      - Lower-weight policy entirely shadowed by a higher-weight policy with same type
        and scope — it will never fire
    """
    errors: list[str] = []
    warnings: list[str] = []

    _check_duplicate_ids(policies, errors)
    _check_weight_conflicts(policies, errors, warnings)

    return ValidationResult(errors=errors, warnings=warnings)


def _check_duplicate_ids(policies: list[Policy], errors: list[str]) -> None:
    seen: dict[str, str] = {}  # policy_id → source_file
    for p in policies:
        if p.policy_id in seen:
            errors.append(
                f"Duplicate policy_id '{p.policy_id}':\n"
                f"    first defined in: {seen[p.policy_id]}\n"
                f"    redefined in:     {p.source_file}\n"
                f"    Fix: each policy_id must be unique across all policy files."
            )
        else:
            seen[p.policy_id] = p.source_file


def _check_weight_conflicts(
    policies: list[Policy],
    errors: list[str],
    warnings: list[str],
) -> None:
    # Group by resource_type
    by_type: dict[str, list[Policy]] = {}
    for p in policies:
        by_type.setdefault(p.resource_type, []).append(p)

    for resource_type, group in by_type.items():
        # Check every pair
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a.weight == b.weight:
                    overlap = _scopes_overlap(
                        a.include, a.exclude, b.include, b.exclude
                    )
                    if overlap:
                        errors.append(
                            f"Conflict between '{a.policy_id}' and '{b.policy_id}':\n"
                            f"    resource_type : {resource_type}\n"
                            f"    weight        : {a.weight} (identical)\n"
                            f"    scope overlap : {overlap}\n"
                            f"    actions       : '{a.action}' vs '{b.action}'\n"
                            f"    source files  : {a.source_file}\n"
                            f"                    {b.source_file}\n"
                            f"    Fix: change one policy's weight, or narrow the scope "
                            f"so they don't overlap."
                        )
                else:
                    # Different weights — check if lower-weight is fully shadowed
                    high, low = (a, b) if a.weight > b.weight else (b, a)
                    if _fully_shadows(high, low):
                        warnings.append(
                            f"Unreachable policy '{low.policy_id}'"
                            f" (weight: {low.weight}):\n"
                            f"    It is fully shadowed by '{high.policy_id}'"
                            f" (weight: {high.weight}),"
                            f" same resource_type '{resource_type}'.\n"
                            f"    The lower-weight policy will never fire.\n"
                            f"    source file: {low.source_file}"
                        )


def _scopes_overlap(
    inc_a: ScopeFilter,
    exc_a: ScopeFilter,
    inc_b: ScopeFilter,
    exc_b: ScopeFilter,
) -> str | None:
    """
    Return a human-readable description of the overlap if the two scope
    pairs can match the same resource, or None if they cannot.

    Conservative: if we cannot prove non-overlap, we assume overlap.
    """
    # Check cloud_platforms
    if inc_a.cloud_platforms and inc_b.cloud_platforms:
        if not set(inc_a.cloud_platforms) & set(inc_b.cloud_platforms):
            return None  # disjoint clouds — no overlap possible

    # Check accounts
    if inc_a.accounts and inc_b.accounts:
        if not set(inc_a.accounts) & set(inc_b.accounts):
            return None  # disjoint accounts

    # Check regions
    if inc_a.regions and inc_b.regions:
        if not set(inc_a.regions) & set(inc_b.regions):
            return None  # disjoint regions

    # Check tags — if both include the same tag key with disjoint values
    tag_map_a = _flatten_tags(inc_a.tags)
    tag_map_b = _flatten_tags(inc_b.tags)
    for key in set(tag_map_a) & set(tag_map_b):
        if not set(tag_map_a[key]) & set(tag_map_b[key]):
            return None  # disjoint tag values for same key

    # Could not prove non-overlap — describe what overlaps
    parts: list[str] = []

    clouds_a = set(inc_a.cloud_platforms or [])
    clouds_b = set(inc_b.cloud_platforms or [])
    common_clouds = (
        clouds_a & clouds_b if (clouds_a and clouds_b) else clouds_a or clouds_b
    )
    if common_clouds:
        parts.append(f"cloud_platforms={sorted(common_clouds)}")

    accts_a = set(inc_a.accounts or [])
    accts_b = set(inc_b.accounts or [])
    common_accts = accts_a & accts_b if (accts_a and accts_b) else accts_a or accts_b
    if common_accts:
        parts.append(f"accounts={sorted(common_accts)}")

    regions_a = set(inc_a.regions or [])
    regions_b = set(inc_b.regions or [])
    common_regions = (
        regions_a & regions_b if (regions_a and regions_b) else regions_a or regions_b
    )
    if common_regions:
        parts.append(f"regions={sorted(common_regions)}")

    if not parts:
        return "all resources (no scope restrictions defined)"

    return ", ".join(parts)


def _fully_shadows(high: Policy, low: Policy) -> bool:
    """
    Return True if high's scope entirely covers low's scope,
    meaning low will never be evaluated for any resource high would match.
    """

    # High must have no include restrictions (matches everything) or
    # its include must be a superset of low's include on every dimension.
    def _covers(
        high_val: tuple | None,
        low_val: tuple | None,
    ) -> bool:
        if high_val is None:
            return True  # high matches all — covers whatever low restricts to
        if low_val is None:
            return False  # low matches all but high is restricted — can't fully shadow
        return set(low_val).issubset(set(high_val))

    if not _covers(high.include.cloud_platforms, low.include.cloud_platforms):
        return False
    if not _covers(high.include.accounts, low.include.accounts):
        return False
    if not _covers(high.include.regions, low.include.regions):
        return False

    return True


def _flatten_tags(tags: tuple[dict[str, list[str]], ...]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in tags:
        for k, v in item.items():
            result.setdefault(k, []).extend(v)
    return result
