from unittest.mock import MagicMock, patch

import pytest

from adapters.azure.resource_graph import _parse_resource, list_resources
from adapters.base import Resource


def _make_raw(
    resource_id: str = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
    name: str = "vm1",
    resource_type: str = "microsoft.compute/virtualmachines",
    location: str = "eastus",
    tags: dict | None = None,
) -> dict:
    return {
        "id": resource_id,
        "name": name,
        "type": resource_type,
        "location": location,
        "resourceGroup": "rg1",
        "tags": tags or {},
        "subscriptionId": "sub1",
    }


class TestParseResource:
    def test_parses_vm(self):
        raw = _make_raw()
        result = _parse_resource(raw, ignore_set=set())
        assert isinstance(result, Resource)
        assert result.resource_type == "microsoft.compute/virtualmachines"
        assert result.cloud == "azure"
        assert result.region == "eastus"
        assert result.name == "vm1"

    def test_returns_none_for_ignored_region(self):
        raw = _make_raw(location="eastus")
        assert _parse_resource(raw, ignore_set={"eastus"}) is None

    def test_returns_none_for_missing_id(self):
        raw = _make_raw(resource_id="")
        assert _parse_resource(raw, ignore_set=set()) is None

    def test_tags_are_normalised_to_str(self):
        raw = _make_raw(tags={"env": "prod", "cost_center": "eng"})
        result = _parse_resource(raw, ignore_set=set())
        assert result.tags == {"env": "prod", "cost_center": "eng"}

    def test_none_tags_produce_empty_dict(self):
        raw = _make_raw(tags=None)
        result = _parse_resource(raw, ignore_set=set())
        assert result.tags == {}

    def test_resource_type_is_lowercased(self):
        raw = _make_raw(resource_type="Microsoft.Compute/VirtualMachines")
        result = _parse_resource(raw, ignore_set=set())
        assert result.resource_type == "microsoft.compute/virtualmachines"


class TestListResources:
    def test_returns_parsed_resources(self):
        mock_response = MagicMock()
        mock_response.data = [_make_raw()]
        mock_response.skip_token = None

        with patch("adapters.azure.resource_graph.ResourceGraphClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.resources.return_value = mock_response

            with patch("adapters.azure.resource_graph.DefaultAzureCredential"):
                resources = list_resources(subscription_ids=["sub1"])

        assert len(resources) == 1
        assert resources[0].name == "vm1"

    def test_raises_permission_error_on_403(self):
        from azure.core.exceptions import HttpResponseError
        exc = HttpResponseError()
        exc.status_code = 403

        with patch("adapters.azure.resource_graph.ResourceGraphClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.resources.side_effect = exc

            with patch("adapters.azure.resource_graph.DefaultAzureCredential"):
                with pytest.raises(PermissionError, match="Reader"):
                    list_resources(subscription_ids=["sub1"])

    def test_excludes_ignored_regions(self):
        mock_response = MagicMock()
        mock_response.data = [_make_raw(location="eastus")]
        mock_response.skip_token = None

        with patch("adapters.azure.resource_graph.ResourceGraphClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.resources.return_value = mock_response

            with patch("adapters.azure.resource_graph.DefaultAzureCredential"):
                resources = list_resources(
                    subscription_ids=["sub1"],
                    ignore_regions=["eastus"],
                )

        assert resources == []
