from __future__ import annotations

from core.config import (
    AISettings,
    AWSSettings,
    AzureSettings,
    GCPSettings,
    ReportSettings,
    ScanSettings,
    clear_settings_cache,
    get_settings,
)


class TestAISettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.delenv("AI_MODEL", raising=False)
        monkeypatch.delenv("AI_TEMPERATURE", raising=False)
        cfg = AISettings()
        assert cfg.provider == "anthropic"
        assert cfg.model is None
        assert cfg.temperature == 0.0

    def test_resolved_model_uses_override(self, monkeypatch):
        monkeypatch.setenv("AI_MODEL", "my-custom-model")
        cfg = AISettings()
        assert cfg.resolved_model("anthropic") == "my-custom-model"
        assert cfg.resolved_model("bedrock") == "my-custom-model"

    def test_resolved_model_falls_back_per_provider(self, monkeypatch):
        monkeypatch.delenv("AI_MODEL", raising=False)
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-custom")
        cfg = AISettings()
        assert cfg.resolved_model("anthropic") == "claude-custom"

    def test_temperature_from_env(self, monkeypatch):
        monkeypatch.setenv("AI_TEMPERATURE", "0.7")
        cfg = AISettings()
        assert cfg.temperature == 0.7


class TestAWSSettings:
    def test_ignore_regions_list(self, monkeypatch):
        monkeypatch.setenv("IGNORE_REGIONS", "ap-east-1, me-south-1")
        cfg = AWSSettings()
        assert cfg.ignore_regions_list == ["ap-east-1", "me-south-1"]

    def test_empty_ignore_regions(self, monkeypatch):
        monkeypatch.setenv("IGNORE_REGIONS", "")
        cfg = AWSSettings()
        assert cfg.ignore_regions_list == []

    def test_accounts_list_parses_json(self, monkeypatch):
        monkeypatch.setenv(
            "ACCOUNTS_CONFIG",
            '[{"id":"111","role_arn":"arn:aws:iam::111:role/R"}]',
        )
        cfg = AWSSettings()
        assert len(cfg.accounts_list) == 1
        assert cfg.accounts_list[0]["id"] == "111"


class TestGCPSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        monkeypatch.delenv("BILLING_BQ_TABLE", raising=False)
        cfg = GCPSettings(_env_file=None)
        assert cfg.project_id == ""
        assert cfg.billing_bq_table is None


class TestAzureSettings:
    def test_subscription_ids_list(self, monkeypatch):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-1, sub-2")
        cfg = AzureSettings()
        assert cfg.subscription_ids_list == ["sub-1", "sub-2"]


class TestReportSettings:
    def test_formats_parses_csv(self, monkeypatch):
        monkeypatch.setenv("REPORT_FORMAT", "json, pdf, pptx")
        cfg = ReportSettings()
        assert cfg.formats == {"json", "pdf", "pptx"}

    def test_dry_run_bool(self, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        cfg = ReportSettings()
        assert cfg.dry_run is True

    def test_has_any_notification_channel(self, monkeypatch):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("WEBHOOK_URL", raising=False)
        cfg = ReportSettings(_env_file=None)
        assert cfg.has_any_notification_channel is False

        monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.com")
        cfg2 = ReportSettings(_env_file=None)
        assert cfg2.has_any_notification_channel is True


class TestScanSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("MAX_RESOURCES_PER_SCAN", raising=False)
        monkeypatch.delenv("ADAPTER_CONCURRENCY", raising=False)
        cfg = ScanSettings()
        assert cfg.max_resources == 200
        assert cfg.adapter_concurrency == 10
        assert cfg.metrics_lookback_days == 90

    def test_override(self, monkeypatch):
        monkeypatch.setenv("MAX_RESOURCES_PER_SCAN", "500")
        monkeypatch.setenv("ADAPTER_CONCURRENCY", "20")
        cfg = ScanSettings()
        assert cfg.max_resources == 500
        assert cfg.adapter_concurrency == 20

    def test_exclude_resource_types_list(self, monkeypatch):
        monkeypatch.setenv("EXCLUDE_RESOURCE_TYPES", "EC2, RDS")
        cfg = ScanSettings()
        assert cfg.exclude_resource_types_list == ["EC2", "RDS"]


class TestGetSettings:
    def test_returns_singleton(self, monkeypatch):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_clear_cache_resets(self, monkeypatch):
        s1 = get_settings()
        clear_settings_cache()
        s2 = get_settings()
        assert s1 is not s2

    def test_top_level_nesting(self, monkeypatch):
        cfg = get_settings()
        assert hasattr(cfg, "ai")
        assert hasattr(cfg, "aws")
        assert hasattr(cfg, "gcp")
        assert hasattr(cfg, "azure")
        assert hasattr(cfg, "report")
        assert hasattr(cfg, "scan")
        assert hasattr(cfg, "log")
