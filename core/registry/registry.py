from __future__ import annotations

from core.registry.models import ResourceTypeSpec


class ResourceRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ResourceTypeSpec] = {}

    def register(self, spec: ResourceTypeSpec) -> None:
        self._specs[spec.type_id] = spec

    def get(self, type_id: str) -> ResourceTypeSpec | None:
        return self._specs.get(type_id)

    def display_name(self, type_id: str) -> str:
        spec = self._specs.get(type_id)
        return spec.display_name if spec else type_id

    def all_for_cloud(self, cloud: str) -> list[ResourceTypeSpec]:
        return [s for s in self._specs.values() if s.cloud == cloud]

    def all_type_ids(self) -> list[str]:
        return list(self._specs.keys())

    def __len__(self) -> int:
        return len(self._specs)
