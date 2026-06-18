from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging() -> None:
    """
    Configure structlog for the current runtime.

    - JSON renderer when stdout is not a TTY (Lambda, Cloud Run, Azure Function).
    - Pretty console renderer when running interactively (local dev / CLI).
    - Log level controlled by LOG_LEVEL env var (default: INFO).

    Call once at the top of each entrypoint before any logger is used.
    stdlib logging is bridged so third-party libraries (boto3, google-cloud, azure)
    also emit structured JSON.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    is_tty = sys.stdout.isatty()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if is_tty:
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Suppress noisy third-party loggers
    for noisy in ("boto3", "botocore", "urllib3", "google", "azure"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
