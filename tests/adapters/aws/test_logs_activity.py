from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from adapters.aws.adapter import AWSAdapter
from adapters.aws.logs_activity import get_last_event, is_log_group, log_group_name
from adapters.base import ActivityUnavailableError

ARN = "arn:aws:logs:eu-west-1:123456789012:log-group:/ecs/pips-core-prod"


def _session(resp=None, error=None):
    client = MagicMock()
    if error:
        client.describe_log_streams.side_effect = ClientError(
            {"Error": {"Code": error, "Message": "x"}}, "DescribeLogStreams"
        )
    else:
        client.describe_log_streams.return_value = resp
    session = MagicMock()
    session.client.return_value = client
    return session, client


def test_newest_stream_event_time_is_the_last_activity():
    ms = int(datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)
    session, client = _session({"logStreams": [{"lastEventTimestamp": ms}]})

    result = get_last_event(session, ARN)

    assert result == datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
    kwargs = client.describe_log_streams.call_args.kwargs
    assert kwargs["logGroupName"] == "/ecs/pips-core-prod"
    assert kwargs["orderBy"] == "LastEventTime" and kwargs["descending"] is True
    assert kwargs["limit"] == 1


def test_a_group_with_no_events_returns_none():
    session, _ = _session({"logStreams": []})
    assert get_last_event(session, ARN) is None
    session, _ = _session({"logStreams": [{"logStreamName": "empty"}]})
    assert get_last_event(session, ARN) is None


@pytest.mark.parametrize(
    "code",
    ["AccessDeniedException", "ThrottlingException", "ResourceNotFoundException"],
)
def test_a_failed_lookup_is_missing_evidence_not_idleness(code):
    session, _ = _session(error=code)

    with patch("adapters.aws.retry.time.sleep"):
        with pytest.raises(ActivityUnavailableError):
            get_last_event(session, ARN)


def test_group_name_is_taken_from_the_arn():
    assert log_group_name(ARN) == "/ecs/pips-core-prod"
    assert log_group_name(ARN + ":*") == "/ecs/pips-core-prod"


def test_log_group_types_are_recognised():
    assert is_log_group("logs:log-group")
    assert is_log_group("AWS::Logs::LogGroup")
    assert not is_log_group("AWS::EC2::Instance")


def test_adapter_uses_cloudwatch_logs_when_cloudtrail_is_empty():
    ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    session, _ = _session({"logStreams": [{"lastEventTimestamp": ms}]})
    adapter = AWSAdapter(session)

    with patch(
        "adapters.aws.adapter.cloudtrail.get_last_activity", return_value=None
    ) as ct:
        result = adapter.get_last_activity(ARN, "logs:log-group")

    assert result is not None
    ct.assert_not_called()


def test_other_types_still_use_cloudtrail():
    adapter = AWSAdapter(MagicMock())
    with patch(
        "adapters.aws.adapter.cloudtrail.get_last_activity", return_value=None
    ) as ct:
        adapter.get_last_activity(
            "arn:aws:ec2:us-east-1:1:instance/i-1", "AWS::EC2::Instance"
        )

    ct.assert_called_once()
