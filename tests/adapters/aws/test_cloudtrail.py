from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from adapters.aws.cloudtrail import _resource_name_from_arn, get_last_activity


def _make_session(events=None, error_code=None):
    mock_client = MagicMock()
    if error_code:
        mock_client.lookup_events.side_effect = ClientError(
            {"Error": {"Code": error_code, "Message": "error"}},
            "LookupEvents",
        )
    else:
        mock_client.lookup_events.return_value = {"Events": events or []}
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    return mock_session, mock_client


class TestResourceNameHelper:
    def test_ec2_instance(self):
        arn = "arn:aws:ec2:us-east-1:123:instance/i-0abc123"
        assert _resource_name_from_arn(arn) == "i-0abc123"

    def test_rds_instance(self):
        arn = "arn:aws:rds:us-east-1:123:db:my-database"
        assert _resource_name_from_arn(arn) == "my-database"

    def test_nat_gateway(self):
        arn = "arn:aws:ec2:us-east-1:123:natgateway/nat-0abc"
        assert _resource_name_from_arn(arn) == "nat-0abc"


class TestGetLastActivity:
    def test_returns_event_time_when_activity_found(self):
        event_time = datetime(2026, 4, 15, 10, 30, 0, tzinfo=timezone.utc)
        session, _ = _make_session(events=[{"EventTime": event_time, "EventName": "StopInstances"}])

        result = get_last_activity(
            session,
            resource_id="arn:aws:ec2:us-east-1:123:instance/i-0abc",
            resource_type="AWS::EC2::Instance",
        )
        assert result == event_time

    def test_returns_none_when_no_events(self):
        session, _ = _make_session(events=[])
        result = get_last_activity(
            session,
            resource_id="arn:aws:ec2:us-east-1:123:instance/i-0abc",
            resource_type="AWS::EC2::Instance",
        )
        assert result is None

    def test_returns_none_on_api_error(self):
        session, _ = _make_session(error_code="InvalidLookupAttributes")
        result = get_last_activity(
            session,
            resource_id="arn:aws:ec2:us-east-1:123:instance/i-0abc",
            resource_type="AWS::EC2::Instance",
        )
        assert result is None

    def test_adds_utc_timezone_to_naive_datetime(self):
        naive_time = datetime(2026, 3, 1, 8, 0, 0)  # no tzinfo
        session, _ = _make_session(events=[{"EventTime": naive_time}])
        result = get_last_activity(
            session,
            resource_id="arn:aws:ec2:us-east-1:123:instance/i-0abc",
            resource_type="AWS::EC2::Instance",
        )
        assert result.tzinfo == timezone.utc
