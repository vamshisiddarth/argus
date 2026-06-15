"""
Central configuration for Argus.
All values come from environment variables — nothing hardcoded.
Load order: .env file → environment → defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of config/)
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path, override=False)  # env vars already set take precedence


def _require(key: str) -> str:
    """Raise at startup if a required env var is missing."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"See .env.example for reference."
        )
    return value


def _csv_list(key: str, default: str = "") -> list[str]:
    """Parse a comma-separated env var into a list of non-empty strings."""
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AWSConfig:
    profile: str | None = field(default_factory=lambda: os.getenv("AWS_PROFILE"))
    primary_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "us-east-1"))
    scan_regions: list[str] = field(
        default_factory=lambda: _csv_list("AWS_SCAN_REGIONS", os.getenv("AWS_REGION", "us-east-1"))
    )


# ---------------------------------------------------------------------------
# GCP
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GCPConfig:
    project_id: str | None = field(default_factory=lambda: os.getenv("GCP_PROJECT_ID"))
    region: str = field(default_factory=lambda: os.getenv("GCP_REGION", "us-central1"))
    credentials_path: str | None = field(
        default_factory=lambda: os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )


# ---------------------------------------------------------------------------
# Bedrock (AI)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BedrockConfig:
    model_id: str = field(
        default_factory=lambda: os.getenv(
            "BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-6"
        )
    )
    region: str = field(default_factory=lambda: os.getenv("BEDROCK_REGION", "us-east-1"))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("BEDROCK_MAX_TOKENS", "2048")))
    temperature: float = field(
        default_factory=lambda: float(os.getenv("BEDROCK_TEMPERATURE", "0.3"))
    )


# ---------------------------------------------------------------------------
# Idle Detection Thresholds
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ThresholdConfig:
    idle_score_threshold: float = field(
        default_factory=lambda: float(os.getenv("IDLE_SCORE_THRESHOLD", "0.7"))
    )
    cpu_threshold_pct: float = field(
        default_factory=lambda: float(os.getenv("IDLE_CPU_THRESHOLD_PCT", "5.0"))
    )
    network_threshold_mb: float = field(
        default_factory=lambda: float(os.getenv("IDLE_NETWORK_THRESHOLD_MB", "5.0"))
    )
    connections_threshold: int = field(
        default_factory=lambda: int(os.getenv("IDLE_CONNECTIONS_THRESHOLD", "1"))
    )
    iops_threshold: float = field(
        default_factory=lambda: float(os.getenv("IDLE_IOPS_THRESHOLD", "1.0"))
    )
    lookback_days: int = field(
        default_factory=lambda: int(os.getenv("IDLE_LOOKBACK_DAYS", "14"))
    )


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    use_tls: bool = field(
        default_factory=lambda: os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    )
    username: str | None = field(default_factory=lambda: os.getenv("SMTP_USERNAME"))
    password: str | None = field(default_factory=lambda: os.getenv("SMTP_PASSWORD"))
    from_address: str = field(
        default_factory=lambda: os.getenv("REPORT_EMAIL_FROM", "argus@localhost")
    )
    to_addresses: list[str] = field(default_factory=lambda: _csv_list("REPORT_EMAIL_TO"))

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.password and self.to_addresses)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SlackConfig:
    webhook_url: str | None = field(default_factory=lambda: os.getenv("SLACK_WEBHOOK_URL"))
    channel: str | None = field(default_factory=lambda: os.getenv("SLACK_CHANNEL"))

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScheduleConfig:
    cron_expression: str = field(
        default_factory=lambda: os.getenv("SCAN_SCHEDULE_CRON", "0 8 * * 1")
    )
    timezone: str = field(default_factory=lambda: os.getenv("SCAN_TIMEZONE", "UTC"))


# ---------------------------------------------------------------------------
# Reporting / Storage
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReportConfig:
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("REPORT_OUTPUT_DIR", "./reports_output"))
    )
    s3_bucket: str | None = field(default_factory=lambda: os.getenv("REPORT_S3_BUCKET") or None)
    s3_prefix: str = field(
        default_factory=lambda: os.getenv("REPORT_S3_PREFIX", "argus/reports/")
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LogConfig:
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    format: str = field(default_factory=lambda: os.getenv("LOG_FORMAT", "json"))
    log_file: str | None = field(default_factory=lambda: os.getenv("LOG_FILE") or None)


# ---------------------------------------------------------------------------
# Top-level Settings (single object imported everywhere)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    dry_run: bool = field(
        default_factory=lambda: os.getenv("DRY_RUN", "false").lower() == "true"
    )
    aws: AWSConfig = field(default_factory=AWSConfig)
    gcp: GCPConfig = field(default_factory=GCPConfig)
    bedrock: BedrockConfig = field(default_factory=BedrockConfig)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    logging: LogConfig = field(default_factory=LogConfig)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


# Module-level singleton — import this everywhere
settings = Settings()
