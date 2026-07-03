from __future__ import annotations

import logging
from functools import lru_cache

from core.registry.aws import AWS_RESOURCE_TYPES
from core.registry.azure import AZURE_RESOURCE_TYPES
from core.registry.gcp import GCP_RESOURCE_TYPES
from core.registry.models import ResourceTypeSpec
from core.registry.registry import ResourceRegistry

logger = logging.getLogger(__name__)

# Ordered list of (name, specs) so failures are attributed to the right cloud.
_CLOUD_BUNDLES: list[tuple[str, list[ResourceTypeSpec]]] = [
    ("aws", AWS_RESOURCE_TYPES),
    ("gcp", GCP_RESOURCE_TYPES),
    ("azure", AZURE_RESOURCE_TYPES),
]


@lru_cache(maxsize=1)
def get_registry() -> ResourceRegistry:
    """Build and return the singleton ResourceRegistry.

    Each cloud bundle is registered independently so a bad entry in one cloud
    does not prevent the other clouds from loading. Registration errors are
    logged at WARNING level and skipped; the caller still gets a functional
    registry for the clouds that loaded cleanly.
    """
    r = ResourceRegistry()
    for cloud, specs in _CLOUD_BUNDLES:
        registered = 0
        for spec in specs:
            try:
                r.register(spec)
                registered += 1
            except ValueError as exc:
                logger.warning(
                    "registry_skip_invalid_spec",
                    extra={"cloud": cloud, "type_id": spec.type_id, "error": str(exc)},
                )
        logger.debug(
            "registry_cloud_loaded",
            extra={"cloud": cloud, "count": registered},
        )
    return r
