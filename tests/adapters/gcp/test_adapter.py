from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from adapters.base import MetricSummary, Resource
from adapters.gcp.adapter import GCPAdapter

SAMPLE_ID = "//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm1"
SAMPLE_TYPE = "compute.googleapis.com/Instance"


def _make_adapter() -> GCPAdapter:
    return GCPAdapter(project_id="my-proj")


class TestGCPAdapterDelegation:
    def test_list_resources_calls_asset_inventory(self):
        adapter = _make_adapter()
        expected = [Resource(SAMPLE_ID, SAMPLE_TYPE, "gcp", "us-central1")]

        with patch(
            "adapters.gcp.adapter.asset_inventory.list_resources",
            return_value=(expected, []),
        ) as mock_fn:
            result = adapter.list_resources()

        mock_fn.assert_called_once_with(project_id="my-proj", ignore_regions=None)
        assert result == expected
        assert adapter.skipped_asset_types == []

    def test_get_metrics_calls_cloud_monitoring(self):
        adapter = _make_adapter()
        expected = MetricSummary(SAMPLE_ID, SAMPLE_TYPE, 14, {"cpu": 0.5})

        with patch(
            "adapters.gcp.adapter.cloud_monitoring.get_metrics", return_value=expected
        ) as mock_fn:
            result = adapter.get_metrics(SAMPLE_ID, SAMPLE_TYPE, days=14)

        mock_fn.assert_called_once_with(
            project_id="my-proj",
            resource_id=SAMPLE_ID,
            resource_type=SAMPLE_TYPE,
            days=14,
        )
        assert result == expected

    def test_get_cost_calls_billing(self):
        adapter = _make_adapter()
        expected = {SAMPLE_ID: 55.00}

        with patch(
            "adapters.gcp.adapter.billing.get_cost", return_value=expected
        ) as mock_fn:
            result = adapter.get_cost([SAMPLE_ID], days=30)

        mock_fn.assert_called_once_with(
            project_id="my-proj",
            resource_ids=[SAMPLE_ID],
            days=30,
            bq_table=None,
        )
        assert result == expected

    def test_get_last_activity_calls_cloud_logging(self):
        adapter = _make_adapter()
        expected = datetime(2026, 5, 1, tzinfo=timezone.utc)

        with patch(
            "adapters.gcp.adapter.cloud_logging.get_last_activity",
            return_value=expected,
        ) as mock_fn:
            result = adapter.get_last_activity(SAMPLE_ID, SAMPLE_TYPE)

        mock_fn.assert_called_once_with(
            project_id="my-proj",
            resource_id=SAMPLE_ID,
            resource_type=SAMPLE_TYPE,
        )
        assert result == expected


class TestGCPAdapterInit:
    def test_raises_without_project_id(self, monkeypatch):
        monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
        with pytest.raises(EnvironmentError, match="GCP_PROJECT_ID"):
            GCPAdapter(project_id=None)

    def test_from_env_reads_project_id(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "env-project")
        adapter = GCPAdapter.from_env()
        assert adapter._project_id == "env-project"
