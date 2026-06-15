from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.azure.adapter import AzureAdapter, _subscription_from_resource_id
from adapters.base import MetricSummary, Resource

SUB = "sub-123"
RID = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
RTYPE = "microsoft.compute/virtualmachines"


def _make_adapter() -> AzureAdapter:
    return AzureAdapter(subscription_ids=[SUB])


class TestSubscriptionExtraction:
    def test_extracts_from_resource_id(self):
        assert _subscription_from_resource_id(RID) == SUB

    def test_returns_empty_for_malformed_id(self):
        assert _subscription_from_resource_id("not-an-azure-id") == ""


class TestAzureAdapterInit:
    def test_raises_without_subscription_ids(self, monkeypatch):
        monkeypatch.delenv("AZURE_SUBSCRIPTION_IDS", raising=False)
        with pytest.raises(EnvironmentError, match="AZURE_SUBSCRIPTION_IDS"):
            AzureAdapter(subscription_ids=None)

    def test_from_env_reads_subscription_ids(self, monkeypatch):
        monkeypatch.setenv("AZURE_SUBSCRIPTION_IDS", "sub-a,sub-b")
        adapter = AzureAdapter.from_env()
        assert adapter._subscription_ids == ["sub-a", "sub-b"]


class TestAzureAdapterDelegation:
    def test_list_resources_calls_resource_graph(self):
        adapter = _make_adapter()
        expected = [Resource(RID, RTYPE, "azure", "eastus")]

        with patch("adapters.azure.adapter.resource_graph.list_resources", return_value=expected) as mock_fn:
            result = adapter.list_resources(ignore_regions=["westus"])

        mock_fn.assert_called_once_with(
            subscription_ids=[SUB],
            ignore_regions=["westus"],
            credential=None,
        )
        assert result == expected

    def test_get_metrics_calls_monitor(self):
        adapter = _make_adapter()
        expected = MetricSummary(RID, RTYPE, 14, {"Percentage CPU": 5.2})

        with patch("adapters.azure.adapter.monitor.get_metrics", return_value=expected) as mock_fn:
            result = adapter.get_metrics(RID, RTYPE, days=14)

        mock_fn.assert_called_once_with(
            resource_id=RID,
            resource_type=RTYPE,
            days=14,
            credential=None,
        )
        assert result == expected

    def test_get_cost_calls_cost_management(self):
        adapter = _make_adapter()
        expected = {RID: 120.00}

        with patch("adapters.azure.adapter.cost_management.get_cost", return_value=expected) as mock_fn:
            result = adapter.get_cost([RID], days=30)

        mock_fn.assert_called_once_with(
            subscription_id=SUB,
            resource_ids=[RID],
            days=30,
            credential=None,
        )
        assert result == expected

    def test_get_last_activity_calls_activity_log(self):
        adapter = _make_adapter()
        expected = datetime(2026, 5, 1, tzinfo=timezone.utc)

        with patch("adapters.azure.adapter.activity_log.get_last_activity", return_value=expected) as mock_fn:
            result = adapter.get_last_activity(RID, RTYPE)

        mock_fn.assert_called_once_with(
            subscription_id=SUB,
            resource_id=RID,
            resource_type=RTYPE,
            credential=None,
        )
        assert result == expected

    def test_get_cost_groups_by_subscription(self):
        adapter = AzureAdapter(subscription_ids=["sub-a", "sub-b"])
        rid_a = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
        rid_b = "/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm2"

        call_args = []
        def capture(**kwargs):
            call_args.append(kwargs["subscription_id"])
            return {rid: 0.0 for rid in kwargs["resource_ids"]}

        with patch("adapters.azure.adapter.cost_management.get_cost", side_effect=capture):
            adapter.get_cost([rid_a, rid_b], days=30)

        assert set(call_args) == {"sub-a", "sub-b"}
