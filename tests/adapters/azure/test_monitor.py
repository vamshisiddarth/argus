from unittest.mock import MagicMock, patch

from adapters.azure.monitor import get_metrics

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
