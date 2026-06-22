from unittest.mock import MagicMock, patch

import pytest

from adapters.gcp.cloud_monitoring import _METRICS, _resource_filter, get_metrics


def _make_time_series(double_values: list[float]) -> list[MagicMock]:
    ts = MagicMock()
    ts.points = []
    for v in double_values:
        point = MagicMock()
        point.value.double_value = v
        point.value.int64_value = 0
        ts.points.append(point)
    return [ts]


class TestResourceFilter:
    def test_compute_instance(self):
        f = _resource_filter(
            "//compute.googleapis.com/projects/p/zones/z/instances/my-vm",
            "compute.googleapis.com/Instance",
        )
        assert 'instance_id="my-vm"' in f

    def test_cloud_sql_instance(self):
        f = _resource_filter(
            "//sqladmin.googleapis.com/projects/p/instances/my-db",
            "sql.googleapis.com/Instance",
        )
        assert 'database_id="my-db"' in f

    def test_unknown_type_returns_empty(self):
        assert (
            _resource_filter("//unknown/resource/name", "unknown.type/Resource") == ""
        )


class TestGetMetrics:
    def test_returns_metric_data_for_known_type(self):
        with patch(
            "adapters.gcp.cloud_monitoring.monitoring_v3.MetricServiceClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_time_series.return_value = _make_time_series(
                [10.0, 20.0, 30.0]
            )

            summary = get_metrics(
                project_id="my-proj",
                resource_id="//compute.googleapis.com/projects/p/zones/z/instances/vm1",
                resource_type="compute.googleapis.com/Instance",
                days=14,
            )

        assert summary.has_data is True
        assert summary.resource_type == "compute.googleapis.com/Instance"
        assert len(summary.metrics) > 0

    def test_returns_has_data_false_when_no_points(self):
        with patch(
            "adapters.gcp.cloud_monitoring.monitoring_v3.MetricServiceClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_time_series.return_value = []

            summary = get_metrics(
                project_id="my-proj",
                resource_id="//compute.googleapis.com/projects/p/zones/z/instances/vm1",
                resource_type="compute.googleapis.com/Instance",
                days=14,
            )

        assert summary.has_data is False

    def test_returns_has_data_false_for_unknown_type_with_no_discovered_metrics(self):
        with patch(
            "adapters.gcp.cloud_monitoring.monitoring_v3.MetricServiceClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_metric_descriptors.return_value = []

            summary = get_metrics(
                project_id="my-proj",
                resource_id="//unknown.googleapis.com/projects/p/things/thing1",
                resource_type="unknown.googleapis.com/Thing",
                days=14,
            )

        assert summary.has_data is False
        assert summary.metrics == {}

    def test_handles_api_error_gracefully(self):
        from google.api_core.exceptions import GoogleAPICallError

        with patch(
            "adapters.gcp.cloud_monitoring.monitoring_v3.MetricServiceClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_time_series.side_effect = GoogleAPICallError(
                "quota exceeded"
            )

            summary = get_metrics(
                project_id="my-proj",
                resource_id="//compute.googleapis.com/projects/p/zones/z/instances/vm1",
                resource_type="compute.googleapis.com/Instance",
                days=14,
            )

        assert summary.has_data is False


# ---------------------------------------------------------------------------
# _METRICS coverage — verify all 31 resource types are registered
# ---------------------------------------------------------------------------
class TestMetricsCoverage:
    def test_metrics_dict_has_31_types(self):
        assert len(_METRICS) == 31

    @pytest.mark.parametrize(
        "resource_type",
        [
            "compute.googleapis.com/Router",
            "compute.googleapis.com/ForwardingRule",
            "compute.googleapis.com/BackendService",
            "compute.googleapis.com/VpnTunnel",
            "compute.googleapis.com/Address",
            "vpcaccess.googleapis.com/Connector",
            "bigtable.googleapis.com/Instance",
            "alloydb.googleapis.com/Cluster",
            "file.googleapis.com/Instance",
            "memcache.googleapis.com/Instance",
            "firestore.googleapis.com/Database",
            "composer.googleapis.com/Environment",
            "notebooks.googleapis.com/Instance",
            "appengine.googleapis.com/Application",
            "cloudtasks.googleapis.com/Queue",
        ],
    )
    def test_new_type_has_metrics(self, resource_type):
        assert resource_type in _METRICS
        assert len(_METRICS[resource_type]) >= 1

    @pytest.mark.parametrize(
        "resource_type",
        [
            "compute.googleapis.com/Router",
            "compute.googleapis.com/ForwardingRule",
            "compute.googleapis.com/BackendService",
            "compute.googleapis.com/VpnTunnel",
            "vpcaccess.googleapis.com/Connector",
            "bigtable.googleapis.com/Instance",
            "alloydb.googleapis.com/Cluster",
            "file.googleapis.com/Instance",
            "memcache.googleapis.com/Instance",
            "composer.googleapis.com/Environment",
            "notebooks.googleapis.com/Instance",
            "cloudtasks.googleapis.com/Queue",
        ],
    )
    def test_new_type_has_resource_filter(self, resource_type):
        f = _resource_filter(
            f"//example.googleapis.com/projects/p/things/my-resource",
            resource_type,
        )
        assert f != "", f"No filter for {resource_type}"
