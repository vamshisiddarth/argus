from __future__ import annotations

from functools import lru_cache

from core.registry.aws import AWS_RESOURCE_TYPES
from core.registry.azure import AZURE_RESOURCE_TYPES
from core.registry.gcp import GCP_RESOURCE_TYPES
from core.registry.registry import ResourceRegistry


@lru_cache(maxsize=1)
def get_registry() -> ResourceRegistry:
    r = ResourceRegistry()
    for spec in AWS_RESOURCE_TYPES + GCP_RESOURCE_TYPES + AZURE_RESOURCE_TYPES:
        r.register(spec)
    return r
