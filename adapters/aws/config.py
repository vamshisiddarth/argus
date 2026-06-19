from __future__ import annotations

from botocore.config import Config

BOTO_TIMEOUT_CONFIG = Config(
    connect_timeout=10,
    read_timeout=60,
    retries={"max_attempts": 0},
)
