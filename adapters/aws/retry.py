from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger(__name__)

T = TypeVar("T")

_MAX_RETRIES = 3
_BASE_DELAY = 1.0

_RETRYABLE_CODES = frozenset(
    {
        "ThrottlingException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "Throttling",
        "InternalError",
        "ServiceUnavailable",
    }
)


def retry_on_transient(
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    delay = _BASE_DELAY
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in _RETRYABLE_CODES and attempt < _MAX_RETRIES - 1:
                jitter = random.uniform(0, delay * 0.5)  # noqa: S311
                sleep_time = delay + jitter
                logger.warning(
                    "aws_transient_error_retrying",
                    error_code=code,
                    attempt=attempt + 1,
                    max_retries=_MAX_RETRIES,
                    retry_in=round(sleep_time, 1),
                )
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise
    raise RuntimeError("Unreachable")  # pragma: no cover
