from unittest.mock import MagicMock, patch

from adapters.gcp.billing import get_cost


class TestGetCost:
    def test_returns_empty_for_no_resource_ids(self):
        assert get_cost("my-proj", []) == {}

    def test_returns_cost_from_bigquery(self):
        row1 = MagicMock()
        row1.resource_name = "my-vm"
        row1.total_cost = 42.50

        with patch(
            "adapters.gcp.billing._query_bigquery",
            return_value={
                "//compute.googleapis.com/projects/p/zones/z/instances/my-vm": 42.50
            },
        ):
            result = get_cost(
                "my-proj",
                ["//compute.googleapis.com/projects/p/zones/z/instances/my-vm"],
                days=30,
            )

        assert (
            result["//compute.googleapis.com/projects/p/zones/z/instances/my-vm"]
            == 42.50
        )

    def test_returns_zeros_on_bq_failure(self):
        rid = "//compute.googleapis.com/projects/p/zones/z/instances/vm1"
        with patch(
            "adapters.gcp.billing._query_bigquery", side_effect=Exception("bq error")
        ):
            result = get_cost("my-proj", [rid], days=30)

        assert result == {rid: 0.0}

    def test_returns_zeros_when_resource_not_in_bq(self):
        rid = "//compute.googleapis.com/projects/p/zones/z/instances/vm1"
        with patch("adapters.gcp.billing._query_bigquery", return_value={rid: 0.0}):
            result = get_cost("my-proj", [rid], days=30)

        assert result[rid] == 0.0
