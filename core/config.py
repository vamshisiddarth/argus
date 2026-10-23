"""
Centralized configuration via pydantic-settings.

All environment variables are defined here with types, defaults, and validation.
Access the singleton via ``get_settings()``. The object is built once and cached
for the lifetime of the process.

Usage::

    from core.config import get_settings
    cfg = get_settings()
    print(cfg.ai.provider)          # "anthropic"
    print(cfg.scan.max_resources)   # 300 (scaled from the $2 default budget)
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    provider: str = Field("anthropic", alias="AI_PROVIDER")
    model: str | None = Field(None, alias="AI_MODEL")
    temperature: float = Field(0.0, alias="AI_TEMPERATURE")
    max_tokens: int = Field(16000, alias="AI_MAX_TOKENS")
    timeout_seconds: float = Field(600.0, alias="AI_TIMEOUT_SECONDS")

    # Anthropic
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    # Bedrock
    bedrock_model_id: str = Field(
        "anthropic.claude-sonnet-4-6", alias="BEDROCK_MODEL_ID"
    )
    bedrock_region: str = Field("us-east-1", alias="BEDROCK_REGION")
    bedrock_max_tokens: int | None = Field(None, alias="BEDROCK_MAX_TOKENS")

    # Vertex AI
    vertexai_project: str | None = Field(None, alias="VERTEXAI_PROJECT")
    vertexai_location: str = Field("us-central1", alias="VERTEXAI_LOCATION")
    vertexai_model: str = Field("google/gemini-1.5-pro-002", alias="VERTEXAI_MODEL")

    # Azure OpenAI
    azure_openai_endpoint: str | None = Field(None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: str = Field("gpt-4o", alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(
        "2024-10-21", alias="AZURE_OPENAI_API_VERSION"
    )
    azure_openai_api_key: str | None = Field(None, alias="AZURE_OPENAI_API_KEY")

    def resolved_model(self, provider: str | None = None) -> str:
        """Return the effective model name for the active (or given) provider."""
        p = provider or self.provider
        if self.model:
            return self.model
        return {
            "anthropic": self.anthropic_model,
            "bedrock": self.bedrock_model_id,
            "vertexai": self.vertexai_model,
            "azure_openai": self.azure_openai_deployment,
        }.get(p, self.anthropic_model)


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------


class AWSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    primary_region: str = Field("us-east-1", alias="PRIMARY_REGION")
    resource_explorer_region: str | None = Field(None, alias="RESOURCE_EXPLORER_REGION")
    ignore_regions: str = Field("", alias="IGNORE_REGIONS")
    accounts_mode: Literal["single", "multi"] = Field("single", alias="ACCOUNTS_MODE")
    accounts_config: str = Field("", alias="ACCOUNTS_CONFIG")
    report_s3_bucket: str = Field("", alias="REPORT_S3_BUCKET")

    @property
    def ignore_regions_list(self) -> list[str]:
        return [r.strip() for r in self.ignore_regions.split(",") if r.strip()]

    @property
    def accounts_list(self) -> list[dict[str, str]]:
        if not self.accounts_config:
            return []
        return list(json.loads(self.accounts_config))


# ---------------------------------------------------------------------------
# GCP
# ---------------------------------------------------------------------------


class GCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    project_id: str = Field("", alias="GCP_PROJECT_ID")
    billing_bq_table: str | None = Field(None, alias="BILLING_BQ_TABLE")
    report_gcs_bucket: str = Field("", alias="REPORT_GCS_BUCKET")


# ---------------------------------------------------------------------------
# Azure
# ---------------------------------------------------------------------------


class AzureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    subscription_ids: str = Field("", alias="AZURE_SUBSCRIPTION_IDS")
    log_analytics_workspace_id: str | None = Field(
        None, alias="AZURE_LOG_ANALYTICS_WORKSPACE_ID"
    )
    report_storage_account: str = Field("", alias="REPORT_STORAGE_ACCOUNT")
    report_storage_container: str = Field(
        "argus-reports", alias="REPORT_STORAGE_CONTAINER"
    )

    @property
    def subscription_ids_list(self) -> list[str]:
        return [s.strip() for s in self.subscription_ids.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Notifications & reports
# ---------------------------------------------------------------------------


class ReportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    slack_webhook_url: str = Field("", alias="SLACK_WEBHOOK_URL")
    teams_webhook_url: str = Field("", alias="TEAMS_WEBHOOK_URL")
    webhook_url: str = Field("", alias="WEBHOOK_URL")
    dry_run: bool = Field(False, alias="DRY_RUN")
    report_format: str = Field("json,html", alias="REPORT_FORMAT")
    report_url_expiry: int = Field(604800, alias="REPORT_URL_EXPIRY")
    local_report_dir: str = Field("local_reports", alias="LOCAL_REPORT_DIR")

    @property
    def formats(self) -> set[str]:
        return {f.strip().lower() for f in self.report_format.split(",") if f.strip()}

    @property
    def has_any_notification_channel(self) -> bool:
        return bool(
            self.slack_webhook_url or self.teams_webhook_url or self.webhook_url
        )


# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------


class RemediationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    # Opt-in: the post-scan runner creates Jira tickets only when this is true.
    # `argus policies apply --confirm` is already explicit and is not gated.
    enabled: bool = Field(False, alias="REMEDIATION_ENABLED")


# ---------------------------------------------------------------------------
# Scan tuning
# ---------------------------------------------------------------------------


# Measured on a real 200-resource scan: about $0.0033 per resource, so 150 per
# dollar of budget keeps a default scan near half the budget.
_RESOURCES_PER_BUDGET_USD = 150
_MIN_AUTO_CAP = 50
_MAX_AUTO_CAP = 1000
_UNLIMITED_BUDGET_CAP = 500


class ScanSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    # Explicit cap; when unset the cap is scaled from the LLM budget (see max_resources)
    max_resources_override: int | None = Field(None, alias="MAX_RESOURCES_PER_SCAN")
    metrics_lookback_days: int = Field(90, alias="METRICS_LOOKBACK_DAYS")
    adapter_concurrency: int = Field(10, alias="ADAPTER_CONCURRENCY")
    max_iterations: int = Field(50, alias="MAX_AGENT_ITERATIONS")
    llm_budget_usd: float = Field(2.0, alias="LLM_BUDGET_USD")
    strict_coverage: bool = Field(False, alias="STRICT_COVERAGE")
    baseline_rules: bool = Field(True, alias="ARGUS_BASELINE_RULES")
    skip_preflight: bool = Field(False, alias="ARGUS_SKIP_PREFLIGHT")
    expect_account: str | None = Field(None, alias="ARGUS_EXPECT_ACCOUNT")
    exclude_tags: str = Field("", alias="EXCLUDE_TAGS")
    exclude_resource_types: str = Field("", alias="EXCLUDE_RESOURCE_TYPES")

    @property
    def max_resources(self) -> int:
        """Resources sent to the AI. Explicit setting wins, else scaled from budget."""
        if self.max_resources_override is not None:
            return self.max_resources_override
        if self.llm_budget_usd <= 0:
            return _UNLIMITED_BUDGET_CAP
        scaled = int(self.llm_budget_usd * _RESOURCES_PER_BUDGET_USD)
        return max(_MIN_AUTO_CAP, min(_MAX_AUTO_CAP, scaled))

    @property
    def max_resources_source(self) -> str:
        return "explicit" if self.max_resources_override is not None else "budget"

    @property
    def exclude_tags_dict(self) -> dict[str, str]:
        if not self.exclude_tags:
            return {}
        return dict(json.loads(self.exclude_tags))

    @property
    def exclude_resource_types_list(self) -> list[str]:
        return [t.strip() for t in self.exclude_resource_types.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class LogSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    log_level: str = Field("INFO", alias="LOG_LEVEL")


# ---------------------------------------------------------------------------
# Top-level settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ai: AISettings = Field(default_factory=AISettings)  # type: ignore[arg-type]
    aws: AWSSettings = Field(default_factory=AWSSettings)  # type: ignore[arg-type]
    gcp: GCPSettings = Field(default_factory=GCPSettings)  # type: ignore[arg-type]
    azure: AzureSettings = Field(default_factory=AzureSettings)  # type: ignore[arg-type]
    report: ReportSettings = Field(default_factory=ReportSettings)  # type: ignore[arg-type]
    scan: ScanSettings = Field(default_factory=ScanSettings)  # type: ignore[arg-type]
    log: LogSettings = Field(default_factory=LogSettings)  # type: ignore[arg-type]
    remediation: RemediationSettings = Field(
        default_factory=RemediationSettings  # type: ignore[arg-type]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance, built from env vars and .env file."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear the cached settings. Useful in tests."""
    get_settings.cache_clear()
