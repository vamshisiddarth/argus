from unittest.mock import MagicMock, patch

import pytest

from adapters.base import Resource
from adapters.gcp.asset_inventory import (
    SCANNED_ASSET_TYPES,
    _parse_asset,
    _to_region,
    list_resources,
)


# ---------------------------------------------------------------------------
# _to_region
# ---------------------------------------------------------------------------
class TestToRegion:
    def test_strips_zone_suffix(self):
        assert _to_region("us-central1-a") == "us-central1"

    def test_returns_region_unchanged(self):
        assert _to_region("us-central1") == "us-central1"

    def test_handles_global(self):
        assert _to_region("global") == "global"

    def test_handles_europe_zone(self):
        assert _to_region("europe-west1-b") == "europe-west1"


# ---------------------------------------------------------------------------
# _parse_asset
# ---------------------------------------------------------------------------
def _make_asset(
    name: str,
    asset_type: str,
    data: dict,
) -> MagicMock:
    asset = MagicMock()
    asset.name = name
    asset.asset_type = asset_type
    asset.resource = MagicMock()
    asset.resource.data = data
    return asset


class TestParseAsset:
    def test_parses_compute_instance(self):
        asset = _make_asset(
            name="//compute.googleapis.com/projects/my-proj/zones/us-central1-a/instances/my-vm",
            asset_type="compute.googleapis.com/Instance",
            data={"name": "my-vm", "zone": "us-central1-a", "labels": {"env": "prod"}},
        )
        result = _parse_asset(asset, ignore_set=set())
        assert isinstance(result, Resource)
        assert result.resource_type == "compute.googleapis.com/Instance"
        assert result.cloud == "gcp"
        assert result.region == "us-central1"
        assert result.name == "my-vm"
        assert result.tags == {"env": "prod"}

    def test_returns_none_when_region_ignored(self):
        asset = _make_asset(
            name="//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm",
            asset_type="compute.googleapis.com/Instance",
            data={"zone": "us-central1-a"},
        )
        assert _parse_asset(asset, ignore_set={"us-central1"}) is None

    def test_returns_none_when_no_resource(self):
        asset = MagicMock()
        asset.resource = None
        assert _parse_asset(asset, ignore_set=set()) is None

    def test_name_falls_back_to_display_name(self):
        asset = _make_asset(
            name="//storage.googleapis.com/projects/p/buckets/my-bucket",
            asset_type="storage.googleapis.com/Bucket",
            data={"displayName": "My Bucket", "location": "us-central1"},
        )
        result = _parse_asset(asset, ignore_set=set())
        assert result.name == "My Bucket"

    def test_empty_labels_produces_empty_tags(self):
        asset = _make_asset(
            name="//compute.googleapis.com/projects/p/zones/us-east1-b/instances/vm",
            asset_type="compute.googleapis.com/Instance",
            data={"zone": "us-east1-b"},
        )
        result = _parse_asset(asset, ignore_set=set())
        assert result.tags == {}


# ---------------------------------------------------------------------------
# list_resources
# ---------------------------------------------------------------------------
class TestListResources:
    def test_returns_parsed_resources(self):
        mock_asset = _make_asset(
            name="//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm1",
            asset_type="compute.googleapis.com/Instance",
            data={"name": "vm1", "zone": "us-central1-a"},
        )
        with patch(
            "adapters.gcp.asset_inventory.asset_v1.AssetServiceClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_assets.return_value = [mock_asset]
            resources = list_resources(project_id="my-proj")

        assert len(resources) == 1
        assert resources[0].name == "vm1"

    def test_raises_permission_error_on_denied(self):
        from google.api_core.exceptions import PermissionDenied

        with patch(
            "adapters.gcp.asset_inventory.asset_v1.AssetServiceClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_assets.side_effect = PermissionDenied("denied")
            with pytest.raises(PermissionError, match="cloudasset"):
                list_resources(project_id="my-proj")

    def test_excludes_ignored_regions(self):
        mock_asset = _make_asset(
            name="//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm1",
            asset_type="compute.googleapis.com/Instance",
            data={"zone": "us-central1-a"},
        )
        with patch(
            "adapters.gcp.asset_inventory.asset_v1.AssetServiceClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_assets.return_value = [mock_asset]
            resources = list_resources(
                project_id="my-proj", ignore_regions=["us-central1"]
            )

        assert resources == []


# ---------------------------------------------------------------------------
# SCANNED_ASSET_TYPES coverage
# ---------------------------------------------------------------------------
class TestAssetTypeCoverage:
    def test_scanned_asset_types_has_31_entries(self):
        assert len(SCANNED_ASSET_TYPES) == 31

    def test_new_types_are_in_scanned_list(self):
        new_types = {
            "compute.googleapis.com/Router",
            "compute.googleapis.com/VpnTunnel",
            "vpcaccess.googleapis.com/Connector",
            "alloydb.googleapis.com/Cluster",
            "firestore.googleapis.com/Database",
            "memcache.googleapis.com/Instance",
            "file.googleapis.com/Instance",
            "appengine.googleapis.com/Application",
            "cloudtasks.googleapis.com/Queue",
        }
        scanned = set(SCANNED_ASSET_TYPES)
        missing = new_types - scanned
        assert not missing, f"Missing from SCANNED_ASSET_TYPES: {missing}"
