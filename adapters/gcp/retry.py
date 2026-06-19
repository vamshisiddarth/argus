from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import structlog
from google.api_core.exceptions import (
    ResourceExhausted,
    ServiceUnavailable,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")

_MAX_RETRIES = 3
_BASE_DELAY = 1.0


def retry_on_transient(
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    delay = _BASE_DELAY
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except (ResourceExhausted, ServiceUnavailable) as exc:
            if attempt < _MAX_RETRIES - 1:
                jitter = random.uniform(0, delay * 0.5)  # noqa: S311
                sleep_time = delay + jitter
                logger.warning(
                    "gcp_transient_error_retrying",
                    error_type=type(exc).__name__,
                    attempt=attempt + 1,
                    max_retries=_MAX_RETRIES,
                    retry_in=round(sleep_time, 1),
                )
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise
    raise RuntimeError("Unreachable")  # pragma: no cover
