from unittest.mock import MagicMock, patch

import pytest

from adapters.azure.monitor import get_metrics
from core.registry import get_registry

SAMPLE_ID = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
SAMPLE_TYPE = "microsoft.compute/virtualmachines"


def _make_metric_response(
    metric_name: str, values: list[float], agg: str = "average"
) -> MagicMock:
    data_points = []
    for v in values:
        dp = MagicMock()
        dp.average = v if agg == "average" else None
        dp.total = v if agg == "total" else None
        data_points.append(dp)

    ts = MagicMock()
    ts.data = data_points

    metric = MagicMock()
    metric.name = metric_name
    metric.timeseries = [ts]

    response = MagicMock()
    response.metrics = [metric]
    return response


class TestGetMetrics:
    def test_returns_averaged_cpu_for_vm(self):
        with patch("adapters.azure.monitor.MetricsQueryClient") as mock_cls:
            with patch("adapters.azure.monitor.DefaultAzureCredential"):
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                mock_client.query_resource.return_value = _make_metric_response(
                    "Percentage CPU", [10.0, 20.0, 30.0], agg="average"
                )

                result = get_metrics(SAMPLE_ID, SAMPLE_TYPE, days=14)

        assert result.has_data is True
        assert result.metrics["Percentage CPU"] == 20.0

    def test_returns_has_data_false_when_no_values(self):
        with patch("adapters.azure.monitor.MetricsQueryClient") as mock_cls:
            with patch("adapters.azure.monitor.DefaultAzureCredential"):
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                response = MagicMock()
                metric = MagicMock()
                metric.name = "Percentage CPU"
                ts = MagicMock()
                ts.data = []
                metric.timeseries = [ts]
                response.metrics = [metric]
                mock_client.query_resource.return_value = response

                result = get_metrics(SAMPLE_ID, SAMPLE_TYPE, days=14)

        assert result.has_data is False

    def test_returns_has_data_false_for_unknown_type_with_no_metrics(self):
        with patch("adapters.azure.monitor.MetricsQueryClient") as mock_cls:
            with patch("adapters.azure.monitor.DefaultAzureCredential"):
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                mock_client.list_metric_definitions.return_value = []

                result = get_metrics(
                    SAMPLE_ID,
                    "microsoft.unknown/resources",
                    days=14,
                )

        assert result.has_data is False
        assert result.metrics == {}

    def test_handles_api_error_gracefully(self):
        from azure.core.exceptions import HttpResponseError

        with patch("adapters.azure.monitor.MetricsQueryClient") as mock_cls:
            with patch("adapters.azure.monitor.DefaultAzureCredential"):
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                exc = HttpResponseError()
                exc.status_code = 400
                mock_client.query_resource.side_effect = exc

                result = get_metrics(SAMPLE_ID, SAMPLE_TYPE, days=14)

        assert result.has_data is False


# ---------------------------------------------------------------------------
# Registry coverage — verify all 40 Azure resource types are in the registry
# ---------------------------------------------------------------------------
class TestMetricsCoverage:
    def test_registry_has_40_azure_types(self):
        registry = get_registry()
        assert len(registry.all_for_cloud("azure")) == 40

    @pytest.mark.parametrize(
        "resource_type",
        [
            "microsoft.network/natgateways",
            "microsoft.network/virtualnetworkgateways",
            "microsoft.network/azurefirewalls",
            "microsoft.network/frontdoors",
            "microsoft.network/expressroutecircuits",
            "microsoft.network/publicipaddresses",
            "microsoft.dbformysql/flexibleservers",
            "microsoft.dbforpostgresql/flexibleservers",
            "microsoft.dbformariadb/servers",
            "microsoft.synapse/workspaces/sqlpools",
            "microsoft.machinelearningservices/workspaces/onlineendpoints",
            "microsoft.batch/batchaccounts",
            "microsoft.devices/iothubs",
            "microsoft.signalrservice/signalr",
        ],
    )
    def test_new_type_has_metrics(self, resource_type):
        spec = get_registry().get(resource_type)
        assert spec is not None
        assert len(spec.metrics) >= 2
