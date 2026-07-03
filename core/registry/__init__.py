from core.registry.factory import get_registry
from core.registry.models import MetricSpec, ResourceTypeSpec
from core.registry.registry import ResourceRegistry

__all__ = ["MetricSpec", "ResourceTypeSpec", "ResourceRegistry", "get_registry"]


def actions_section(
    cloud: str,
    filter_actions: list[str] | None = None,
    min_cost_usd: float | None = None,
) -> str:
    """Return a formatted REMEDIATION ACTIONS section for the agent prompt.

    Lists resource types for the given cloud alongside the actions the AI should
    recommend — sourced entirely from the registry, never hardcoded in the prompt.

    Args:
        cloud: "aws", "gcp", or "azure".
        filter_actions: if provided, only include types that support ALL of these
            actions (e.g. ["resize"] to show only right-sizable types).
        min_cost_usd: if provided, only include types whose typical_monthly_cost_usd
            is at or above this threshold (unknown costs are always included).
    """
    registry = get_registry()
    specs = registry.all_for_cloud(cloud)

    if filter_actions:
        required = set(filter_actions)
        specs = [s for s in specs if required.issubset(set(s.actions))]

    if min_cost_usd is not None:
        specs = [
            s
            for s in specs
            if s.typical_monthly_cost_usd is None
            or s.typical_monthly_cost_usd >= min_cost_usd
        ]

    specs = sorted(specs, key=lambda s: s.service)
    if not specs:
        return ""

    lines = ["REMEDIATION ACTIONS (registry-driven)", "─" * 38]
    current_service = ""
    for spec in specs:
        if spec.service != current_service:
            current_service = spec.service
            lines.append(f"\n  {spec.service}")
        action_str = ", ".join(spec.actions) if spec.actions else "review"
        lines.append(f"    {spec.display_name:<40} → {action_str}")
    return "\n".join(lines)
