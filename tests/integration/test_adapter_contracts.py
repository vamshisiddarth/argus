"""
Adapter contract tests — verify each adapter's methods return correct types
and shapes regardless of the underlying cloud SDK.

These catch wiring bugs, serialization issues, and interface violations that
unit tests with per-method mocks can't see.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from adapters.base import MetricSummary, Resource

# Import the fixture data
from tests.integration.conftest import (
    AWS_RESOURCES,
    AZURE_RESOURCES,
    COSTS,
    GCP_RESOURCES,
)


@pytest.mark.integration
class TestAdapterContractAWS:
    def test_list_resources_returns_resource_objects(self, aws_adapter):
        resources = aws_adapter.list_resources(ignore_regions=None)
        assert len(resources) == len(AWS_RESOURCES)
        for r in resources:
            assert isinstance(r, Resource)
            assert r.cloud == "aws"
            assert r.resource_id
            assert r.resource_type
            assert r.region

    def test_get_cost_returns_dict_of_floats(self, aws_adapter):
        ids = [r.resource_id for r in AWS_RESOURCES]
        costs = aws_adapter.get_cost(resource_ids=ids)
        assert isinstance(costs, dict)
        for rid, cost in costs.items():
            assert isinstance(rid, str)
            assert isinstance(cost, (int, float))
            assert cost >= 0

    def test_get_metrics_returns_metric_summary(self, aws_adapter):
        r = AWS_RESOURCES[0]
        summary = aws_adapter.get_metrics(
            resource_id=r.resource_id, resource_type=r.resource_type
        )
        assert isinstance(summary, MetricSummary)
        assert summary.resource_id == r.resource_id
        assert summary.period_days > 0
        assert isinstance(summary.metrics, dict)

    def test_get_last_activity_returns_datetime_or_none(self, aws_adapter):
        r = AWS_RESOURCES[0]
        result = aws_adapter.get_last_activity(
            resource_id=r.resource_id, resource_type=r.resource_type
        )
        assert result is None or isinstance(result, datetime)

    def test_resource_to_dict_roundtrip(self):
        for r in AWS_RESOURCES:
            d = r.to_dict()
            assert d["resource_id"] == r.resource_id
            assert d["resource_type"] == r.resource_type
            assert d["cloud"] == r.cloud
            assert d["region"] == r.region
            assert isinstance(d["tags"], dict)


@pytest.mark.integration
class TestAdapterContractGCP:
    def test_list_resources_returns_resource_objects(self, gcp_adapter):
        resources = gcp_adapter.list_resources(ignore_regions=None)
        assert len(resources) == len(GCP_RESOURCES)
        for r in resources:
            assert isinstance(r, Resource)
            assert r.cloud == "gcp"

    def test_get_cost_returns_dict_of_floats(self, gcp_adapter):
        ids = [r.resource_id for r in GCP_RESOURCES]
        costs = gcp_adapter.get_cost(resource_ids=ids)
        assert isinstance(costs, dict)
        assert all(isinstance(v, (int, float)) for v in costs.values())

    def test_get_metrics_returns_metric_summary(self, gcp_adapter):
        r = GCP_RESOURCES[0]
        summary = gcp_adapter.get_metrics(
            resource_id=r.resource_id, resource_type=r.resource_type
        )
        assert isinstance(summary, MetricSummary)

    def test_get_last_activity_returns_datetime_or_none(self, gcp_adapter):
        r = GCP_RESOURCES[0]
        result = gcp_adapter.get_last_activity(
            resource_id=r.resource_id, resource_type=r.resource_type
        )
        assert result is None or isinstance(result, datetime)


@pytest.mark.integration
class TestAdapterContractAzure:
    def test_list_resources_returns_resource_objects(self, azure_adapter):
        resources = azure_adapter.list_resources(ignore_regions=None)
        assert len(resources) == len(AZURE_RESOURCES)
        for r in resources:
            assert isinstance(r, Resource)
            assert r.cloud == "azure"

    def test_get_cost_returns_dict_of_floats(self, azure_adapter):
        ids = [r.resource_id for r in AZURE_RESOURCES]
        costs = azure_adapter.get_cost(resource_ids=ids)
        assert isinstance(costs, dict)
        assert all(isinstance(v, (int, float)) for v in costs.values())

    def test_get_metrics_returns_metric_summary(self, azure_adapter):
        r = AZURE_RESOURCES[0]
        summary = azure_adapter.get_metrics(
            resource_id=r.resource_id, resource_type=r.resource_type
        )
        assert isinstance(summary, MetricSummary)

    def test_get_last_activity_returns_datetime_or_none(self, azure_adapter):
        r = AZURE_RESOURCES[0]
        result = azure_adapter.get_last_activity(
            resource_id=r.resource_id, resource_type=r.resource_type
        )
        assert result is None or isinstance(result, datetime)
