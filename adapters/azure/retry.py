from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import structlog
from azure.core.exceptions import HttpResponseError

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
        except HttpResponseError as exc:
            status = exc.status_code or 0
            if status in (429, 500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                retry_after = _parse_retry_after(exc)
                jitter = random.uniform(0, delay * 0.5)  # noqa: S311
                sleep_time = retry_after if retry_after else delay + jitter
                logger.warning(
                    "azure_transient_error_retrying",
                    status_code=status,
                    attempt=attempt + 1,
                    max_retries=_MAX_RETRIES,
                    retry_in=round(sleep_time, 1),
                )
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise
    raise RuntimeError("Unreachable")  # pragma: no cover


def _parse_retry_after(exc: HttpResponseError) -> float | None:
    if exc.response is None:
        return None
    header = exc.response.headers.get("Retry-After")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None
