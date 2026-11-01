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
        response = _make_ce_response(
            [
                {
                    "Keys": ["i-0abc123"],
                    "Metrics": {"UnblendedCost": {"Amount": "15.23", "Unit": "USD"}},
                },
                {
                    "Keys": ["nat-0def456"],
                    "Metrics": {"UnblendedCost": {"Amount": "94.10", "Unit": "USD"}},
                },
            ]
        )
        session, _ = _make_session(response=response)
        costs = get_cost(session, resource_ids=["i-0abc123", "nat-0def456"])

        assert costs["i-0abc123"] == pytest.approx(15.23)
        assert costs["nat-0def456"] == pytest.approx(94.10)

    def test_returns_zero_for_resources_with_no_cost_data(self):
        response = _make_ce_response(
            [
                {
                    "Keys": ["i-0abc123"],
                    "Metrics": {"UnblendedCost": {"Amount": "10.00", "Unit": "USD"}},
                },
            ]
        )
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
            error_message="User: missing ce:GetCostAndUsageWithResources",
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


OPT_IN_MESSAGE = (
    "Resource-level data granularity is an opt-in feature. You can enable it "
    "from the PAYER account in Cost Explorer settings."
)


@pytest.fixture(autouse=True)
def _reset_warned():
    from adapters.aws import cost_explorer

    cost_explorer._warned.clear()
    yield
    cost_explorer._warned.clear()


class TestResourceLevelWindow:
    def test_window_is_clamped_to_14_days(self):
        from datetime import datetime, timedelta, timezone

        session, client = _make_session(response=_make_ce_response([]))

        get_cost(session, resource_ids=["i-1"], days=30)

        period = client.get_cost_and_usage_with_resources.call_args.kwargs["TimePeriod"]
        end = datetime.fromisoformat(period["End"]).date()
        start = datetime.fromisoformat(period["Start"]).date()
        assert (end - start) == timedelta(days=14)
        assert end == datetime.now(tz=timezone.utc).date()

    def test_shorter_requests_are_left_alone(self):
        from datetime import datetime

        session, client = _make_session(response=_make_ce_response([]))

        get_cost(session, resource_ids=["i-1"], days=7)

        period = client.get_cost_and_usage_with_resources.call_args.kwargs["TimePeriod"]
        delta = datetime.fromisoformat(period["End"]) - datetime.fromisoformat(
            period["Start"]
        )
        assert delta.days == 7


class TestCostExplorerMessages:
    def _events(self, error_code, message, calls=1):
        from structlog.testing import capture_logs

        session, _ = _make_session(error_code=error_code, error_message=message)
        with capture_logs() as logs:
            for _ in range(calls):
                get_cost(session, resource_ids=["i-1"])
        return logs

    def test_opt_in_error_points_at_the_payer_account_not_iam(self):
        logs = self._events("AccessDeniedException", OPT_IN_MESSAGE)

        events = [e["event"] for e in logs]
        assert "cost_explorer_resource_level_not_enabled" in events
        assert "cost_explorer_access_denied" not in events
        hint = next(e for e in logs if "hint" in e)["hint"]
        assert "PAYER" in hint or "payer" in hint

    def test_real_iam_denial_keeps_the_permission_hint(self):
        logs = self._events(
            "AccessDeniedException", "User is not authorized to perform ce:Get"
        )

        events = [e["event"] for e in logs]
        assert "cost_explorer_access_denied" in events
        assert "cost_explorer_resource_level_not_enabled" not in events

    def test_the_same_failure_is_logged_once(self):
        logs = self._events("AccessDeniedException", OPT_IN_MESSAGE, calls=3)

        warnings = [e for e in logs if e["event"].startswith("cost_explorer")]
        assert len(warnings) == 1

    def test_returns_zeros_for_every_failure_kind(self):
        session, _ = _make_session(
            error_code="AccessDeniedException", error_message=OPT_IN_MESSAGE
        )
        assert get_cost(session, resource_ids=["a", "b"]) == {"a": 0.0, "b": 0.0}


class TestProbeResourceLevelCost:
    def test_ok_when_the_call_succeeds(self):
        from adapters.aws.cost_explorer import probe_resource_level_cost

        session, _ = _make_session(response=_make_ce_response([]))
        assert probe_resource_level_cost(session) is None

    def test_opt_in_missing_is_reported_with_payer_hint(self):
        from adapters.aws.cost_explorer import probe_resource_level_cost

        session, _ = _make_session(
            error_code="AccessDeniedException", error_message=OPT_IN_MESSAGE
        )
        assert "PAYER" in probe_resource_level_cost(session).upper()

    def test_iam_denial_is_reported_as_permission(self):
        from adapters.aws.cost_explorer import probe_resource_level_cost

        session, _ = _make_session(
            error_code="AccessDeniedException", error_message="not authorized"
        )
        assert "ce:GetCostAndUsageWithResources" in probe_resource_level_cost(session)
