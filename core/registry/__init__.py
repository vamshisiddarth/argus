from core.registry.factory import get_registry
from core.registry.models import MetricSpec, ResourceTypeSpec
from core.registry.registry import ResourceRegistry

__all__ = ["MetricSpec", "ResourceTypeSpec", "ResourceRegistry", "get_registry"]


def actions_section(cloud: str) -> str:
    """Return a formatted REMEDIATION ACTIONS section for the agent prompt.

    Lists every known resource type for the given cloud alongside the actions
    the AI should recommend — sourced entirely from the registry, never hardcoded
    in the prompt text.
    """
    registry = get_registry()
    specs = sorted(registry.all_for_cloud(cloud), key=lambda s: s.service)
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
