from __future__ import annotations

from core.registry.models import ResourceTypeSpec

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


class ResourceRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ResourceTypeSpec] = {}

    def register(self, spec: ResourceTypeSpec) -> None:
        if not spec.type_id:
            raise ValueError("ResourceTypeSpec.type_id must not be empty")
        if not spec.display_name:
            raise ValueError(
                f"ResourceTypeSpec.display_name must not be empty for {spec.type_id!r}"
            )
        unknown = set(spec.actions) - _VALID_ACTIONS
        if unknown:
            raise ValueError(
                f"Unknown actions {unknown!r} for {spec.type_id!r}. "
                f"Valid: {sorted(_VALID_ACTIONS)}"
            )
        self._specs[spec.type_id] = spec

    def get(self, type_id: str) -> ResourceTypeSpec | None:
        return self._specs.get(type_id)

    def display_name(self, type_id: str) -> str:
        spec = self._specs.get(type_id)
        return spec.display_name if spec else type_id

    def all_for_cloud(self, cloud: str) -> list[ResourceTypeSpec]:
        return [s for s in self._specs.values() if s.cloud == cloud]

    def all_for_action(self, action: str) -> list[ResourceTypeSpec]:
        """Return all specs that support the given remediation action."""
        return [s for s in self._specs.values() if action in s.actions]

    def actions_for(self, type_id: str) -> tuple[str, ...]:
        """Return the actions tuple for a type_id, or empty tuple if not found."""
        spec = self._specs.get(type_id)
        return spec.actions if spec else ()

    def all_type_ids(self) -> list[str]:
        return list(self._specs.keys())

    def __len__(self) -> int:
        return len(self._specs)
