"""
Integration-style tests for AWSAdapter.
Verifies the adapter correctly wires all sub-modules together.
Each sub-module is mocked so no real AWS calls are made.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from adapters.aws.adapter import AWSAdapter
from adapters.base import MetricSummary, Resource

SAMPLE_ARN = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123"
SAMPLE_TYPE = "AWS::EC2::Instance"


def _make_adapter() -> tuple[AWSAdapter, MagicMock]:
    session = MagicMock()
    adapter = AWSAdapter(session=session, aggregator_region="us-east-1")
    return adapter, session


class TestAWSAdapterDelegation:
    def test_list_resources_calls_resource_explorer(self):
        adapter, _ = _make_adapter()
        expected = [Resource(SAMPLE_ARN, SAMPLE_TYPE, "aws", "us-east-1")]

        with patch(
            "adapters.aws.adapter.resource_explorer.list_resources",
            return_value=expected,
        ) as mock_fn:
            result = adapter.list_resources(ignore_regions=[])

        mock_fn.assert_called_once()
        assert result == expected

    def test_get_metrics_calls_cloudwatch(self):
        adapter, _ = _make_adapter()
        expected = MetricSummary(SAMPLE_ARN, SAMPLE_TYPE, 14, {"CPUUtilization": 0.9})

        with patch(
            "adapters.aws.adapter.cloudwatch.get_metrics", return_value=expected
        ) as mock_fn:
            result = adapter.get_metrics(SAMPLE_ARN, SAMPLE_TYPE, days=14)

        mock_fn.assert_called_once_with(
            session=adapter._session,
            resource_id=SAMPLE_ARN,
            resource_type=SAMPLE_TYPE,
            days=14,
        )
        assert result == expected

    def test_get_cost_calls_cost_explorer(self):
        adapter, _ = _make_adapter()
        expected = {SAMPLE_ARN: 45.60}

        with patch(
            "adapters.aws.adapter.cost_explorer.get_cost", return_value=expected
        ) as mock_fn:
            result = adapter.get_cost([SAMPLE_ARN], days=30)

        mock_fn.assert_called_once_with(
            session=adapter._session,
            resource_ids=[SAMPLE_ARN],
            days=30,
        )
        assert result == expected

    def test_get_last_activity_calls_cloudtrail(self):
        adapter, _ = _make_adapter()
        expected = datetime(2026, 5, 1, tzinfo=timezone.utc)

        with patch(
            "adapters.aws.adapter.cloudtrail.get_last_activity", return_value=expected
        ) as mock_fn:
            result = adapter.get_last_activity(SAMPLE_ARN, SAMPLE_TYPE)

        mock_fn.assert_called_once_with(
            session=adapter._session,
            resource_id=SAMPLE_ARN,
            resource_type=SAMPLE_TYPE,
        )
        assert result == expected


class TestForAccountClassMethod:
    def test_creates_adapter_via_auth(self):
        mock_session = MagicMock()
        with patch(
            "adapters.aws.adapter.auth.get_session", return_value=mock_session
        ) as mock_auth:
            adapter = AWSAdapter.for_account(account=None, region="eu-west-1")

        mock_auth.assert_called_once_with(account=None, region="eu-west-1")
        assert isinstance(adapter, AWSAdapter)
        assert adapter._session is mock_session
