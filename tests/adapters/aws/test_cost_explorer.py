from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from adapters.aws.cost_explorer import get_cost


def _make_ce_response(groups: list[dict]) -> dict:
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-05-06", "End": "2026-06-06"},
                "Groups": groups,
                "Estimated": False,
            }
        ]
    }


def _make_session(response=None, error_code=None, error_message="error"):
    mock_client = MagicMock()
    if error_code:
        mock_client.get_cost_and_usage_with_resources.side_effect = ClientError(
            {"Error": {"Code": error_code, "Message": error_message}},
            "GetCostAndUsageWithResources",
        )
    else:
        mock_client.get_cost_and_usage_with_resources.return_value = response
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    return mock_session, mock_client


class TestGetCost:
    def test_returns_cost_per_resource(self):
        response = _make_ce_response([
            {"Keys": ["i-0abc123"], "Metrics": {"UnblendedCost": {"Amount": "15.23", "Unit": "USD"}}},
            {"Keys": ["nat-0def456"], "Metrics": {"UnblendedCost": {"Amount": "94.10", "Unit": "USD"}}},
        ])
        session, _ = _make_session(response=response)
        costs = get_cost(session, resource_ids=["i-0abc123", "nat-0def456"])

        assert costs["i-0abc123"] == pytest.approx(15.23)
        assert costs["nat-0def456"] == pytest.approx(94.10)

    def test_returns_zero_for_resources_with_no_cost_data(self):
        response = _make_ce_response([
            {"Keys": ["i-0abc123"], "Metrics": {"UnblendedCost": {"Amount": "10.00", "Unit": "USD"}}},
        ])
        session, _ = _make_session(response=response)
        costs = get_cost(session, resource_ids=["i-0abc123", "vol-orphan"])

        assert costs["vol-orphan"] == 0.0

    def test_returns_zeros_on_data_unavailable_exception(self):
        session, _ = _make_session(error_code="DataUnavailableException")
        costs = get_cost(session, resource_ids=["i-0abc123", "nat-0def"])

        assert costs == {"i-0abc123": 0.0, "nat-0def": 0.0}

    def test_returns_zeros_when_cost_explorer_not_activated(self):
        session, _ = _make_session(
            error_code="AccessDeniedException",
            error_message="User not enabled for cost explorer access",
        )
        costs = get_cost(session, resource_ids=["i-0abc123"])
        assert costs == {"i-0abc123": 0.0}

    def test_returns_zeros_on_iam_access_denied(self):
        session, _ = _make_session(
            error_code="AccessDeniedException",
            error_message="User is not authorized to perform ce:GetCostAndUsageWithResources",
        )
        costs = get_cost(session, resource_ids=["i-0abc123"])
        assert costs == {"i-0abc123": 0.0}

    def test_returns_zeros_on_generic_error(self):
        session, _ = _make_session(error_code="InternalServerError")
        costs = get_cost(session, resource_ids=["i-0abc123"])
        assert costs == {"i-0abc123": 0.0}

    def test_returns_empty_dict_for_no_resource_ids(self):
        session = MagicMock()
        costs = get_cost(session, resource_ids=[])
        assert costs == {}
        session.client.assert_not_called()

    def test_batches_all_ids_in_single_api_call(self):
        response = _make_ce_response([])
        session, mock_client = _make_session(response=response)
        resource_ids = [f"i-{i:010d}" for i in range(50)]
        get_cost(session, resource_ids=resource_ids)

        # Must be exactly ONE API call regardless of how many IDs
        assert mock_client.get_cost_and_usage_with_resources.call_count == 1
        call_args = mock_client.get_cost_and_usage_with_resources.call_args.kwargs
        assert call_args["Filter"]["Dimensions"]["Values"] == resource_ids
