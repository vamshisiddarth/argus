from unittest.mock import MagicMock, patch

from adapters.azure.cost_management import get_cost

SUB = "sub-123"
RID = "/subscriptions/sub-123/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"


class TestGetCost:
    def test_returns_empty_for_no_resource_ids(self):
        assert get_cost(SUB, []) == {}

    def test_returns_cost_per_resource(self):
        with patch("adapters.azure.cost_management._query_batch") as mock_query:
            def fill_costs(client, scope, batch, days, costs):
                costs[RID] = 88.50
            mock_query.side_effect = fill_costs

            with patch("adapters.azure.cost_management.CostManagementClient"):
                with patch("adapters.azure.cost_management.DefaultAzureCredential"):
                    result = get_cost(SUB, [RID], days=30)

        assert result[RID] == 88.50

    def test_returns_zeros_on_403(self):
        from azure.core.exceptions import HttpResponseError
        exc = HttpResponseError()
        exc.status_code = 403

        with patch("adapters.azure.cost_management._query_batch", side_effect=exc):
            with patch("adapters.azure.cost_management.CostManagementClient"):
                with patch("adapters.azure.cost_management.DefaultAzureCredential"):
                    result = get_cost(SUB, [RID], days=30)

        assert result == {RID: 0.0}

    def test_batches_large_resource_lists(self):
        rids = [f"/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm{i}" for i in range(120)]

        call_count = []
        def record_call(client, scope, batch, days, costs):
            call_count.append(len(batch))

        with patch("adapters.azure.cost_management._query_batch", side_effect=record_call):
            with patch("adapters.azure.cost_management.CostManagementClient"):
                with patch("adapters.azure.cost_management.DefaultAzureCredential"):
                    get_cost(SUB, rids, days=30)

        # 120 resources with batch size 50 → 3 batches
        assert len(call_count) == 3
        assert call_count[0] == 50
        assert call_count[1] == 50
        assert call_count[2] == 20
