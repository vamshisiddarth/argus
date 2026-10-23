import json
from unittest.mock import MagicMock

import pytest

from adapters.aws.resource_explorer import (
    _is_billable,
    _parse_resource,
    _parse_tags,
    discover,
    list_resources,
    list_resources_with_status,
)


def _make_raw_resource(
    arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123",
    resource_type="AWS::EC2::Instance",
    region="us-east-1",
    tags=None,
):
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]
    return {
        "Arn": arn,
        "ResourceType": resource_type,
        "Region": region,
        "Service": "ec2",
        "Properties": [{"Name": "tags", "Data": json.dumps(tag_list)}],
    }


class TestIsBillable:
    def test_ec2_instance_is_billable(self):
        assert _is_billable("AWS::EC2::Instance") is True

    def test_rds_is_billable(self):
        assert _is_billable("AWS::RDS::DBInstance") is True

    def test_lambda_function_is_billable(self):
        assert _is_billable("AWS::Lambda::Function") is True

    def test_iam_role_is_not_billable(self):
        assert _is_billable("AWS::IAM::Role") is False

    def test_iam_policy_is_not_billable(self):
        assert _is_billable("AWS::IAM::ManagedPolicy") is False

    def test_subnet_is_not_billable(self):
        assert _is_billable("AWS::EC2::Subnet") is False

    def test_route_table_is_not_billable(self):
        assert _is_billable("AWS::EC2::RouteTable") is False

    def test_cloudformation_stack_is_not_billable(self):
        assert _is_billable("AWS::CloudFormation::Stack") is False

    def test_lambda_event_source_mapping_is_not_billable(self):
        assert _is_billable("AWS::Lambda::EventSourceMapping") is False

    def test_case_insensitive(self):
        # Resource Explorer returns mixed case — filter must be case-insensitive
        assert _is_billable("aws::iam::role") is False
        assert _is_billable("AWS::IAM::ROLE") is False


class TestParseTagsHelper:
    def test_parses_tags_correctly(self):
        properties = [
            {
                "Name": "tags",
                "Data": json.dumps(
                    [
                        {"Key": "Name", "Value": "web-01"},
                        {"Key": "Env", "Value": "prod"},
                    ]
                ),
            }
        ]
        assert _parse_tags(properties) == {"Name": "web-01", "Env": "prod"}

    def test_returns_empty_dict_when_no_tags(self):
        assert _parse_tags([]) == {}

    def test_handles_malformed_json_gracefully(self):
        assert _parse_tags([{"Name": "tags", "Data": "not-json"}]) == {}


class TestParseResourceHelper:
    def test_parses_ec2_instance(self):
        raw = _make_raw_resource(tags={"Name": "my-server", "Env": "staging"})
        result = _parse_resource(raw)

        assert result is not None
        assert (
            result.resource_id
            == "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123"
        )
        assert result.resource_type == "AWS::EC2::Instance"
        assert result.cloud == "aws"
        assert result.region == "us-east-1"
        assert result.name == "my-server"
        assert result.tags == {"Name": "my-server", "Env": "staging"}

    def test_returns_none_for_missing_arn(self):
        assert (
            _parse_resource(
                {"ResourceType": "AWS::EC2::Instance", "Region": "us-east-1"}
            )
            is None
        )

    def test_name_is_none_when_no_name_tag(self):
        raw = _make_raw_resource(tags={"Env": "prod"})
        result = _parse_resource(raw)
        assert result is not None
        assert result.name is None


class TestListResources:
    def _make_mock_session(self, pages):
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = iter(pages)
        mock_client = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client
        return mock_session, mock_client

    def test_returns_all_resources_across_pages(self):
        pages = [
            {"Resources": [_make_raw_resource(region="us-east-1")]},
            {
                "Resources": [
                    _make_raw_resource(
                        arn="arn:aws:ec2:us-west-2:123:instance/i-0def456",
                        region="us-west-2",
                    )
                ]
            },
        ]
        session, _ = self._make_mock_session(pages)
        results = list_resources(session, ignore_regions=[])
        assert len(results) == 2

    def test_excludes_ignored_regions(self):
        pages = [
            {
                "Resources": [
                    _make_raw_resource(region="us-east-1"),
                    _make_raw_resource(
                        arn="arn:aws:ec2:eu-west-1:123:instance/i-0def456",
                        region="eu-west-1",
                    ),
                ]
            }
        ]
        session, _ = self._make_mock_session(pages)
        results = list_resources(session, ignore_regions=["eu-west-1"])
        assert len(results) == 1
        assert results[0].region == "us-east-1"

    def test_returns_all_regions_when_ignore_list_is_empty(self):
        pages = [
            {
                "Resources": [
                    _make_raw_resource(region="us-east-1"),
                    _make_raw_resource(
                        arn="arn:aws:ec2:eu-west-1:123:instance/i-xyz",
                        region="eu-west-1",
                    ),
                ]
            }
        ]
        session, _ = self._make_mock_session(pages)
        results = list_resources(session, ignore_regions=[])
        assert len(results) == 2

    def test_returns_all_regions_when_ignore_list_is_none(self):
        pages = [
            {
                "Resources": [
                    _make_raw_resource(region="us-east-1"),
                    _make_raw_resource(
                        arn="arn:aws:ec2:ap-southeast-1:123:instance/i-xyz",
                        region="ap-southeast-1",
                    ),
                ]
            }
        ]
        session, _ = self._make_mock_session(pages)
        results = list_resources(session)  # no ignore_regions arg at all
        assert len(results) == 2

    def test_filters_out_non_billable_resource_types(self):
        """IAM roles, subnets, route tables etc. should never reach the AI."""
        pages = [
            {
                "Resources": [
                    _make_raw_resource(
                        arn="arn:aws:ec2:us-east-1:123:instance/i-0abc",
                        resource_type="AWS::EC2::Instance",
                        region="us-east-1",
                    ),
                    _make_raw_resource(
                        arn="arn:aws:iam::123:role/MyRole",
                        resource_type="AWS::IAM::Role",
                        region="us-east-1",
                    ),
                    _make_raw_resource(
                        arn="arn:aws:ec2:us-east-1:123:subnet/subnet-abc",
                        resource_type="AWS::EC2::Subnet",
                        region="us-east-1",
                    ),
                ]
            }
        ]
        session, _ = self._make_mock_session(pages)
        results = list_resources(session, ignore_regions=[])
        assert len(results) == 1
        assert results[0].resource_type == "AWS::EC2::Instance"

    def test_raises_permission_error_on_access_denied(self):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}},
            "Search",
        )
        mock_client.get_paginator.return_value = mock_paginator
        mock_client.exceptions.AccessDeniedException = ClientError
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        with pytest.raises(PermissionError):
            list_resources(mock_session, ignore_regions=[])


class TestSearchLimit:
    def _session(self, n: int):
        raw = [
            _make_raw_resource(arn=f"arn:aws:ec2:us-east-1:1:volume/vol-{i}")
            for i in range(n)
        ]
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {"Resources": raw[:500]},
            {"Resources": raw[500:]},
        ]
        session = MagicMock()
        session.client.return_value = client
        session.get_available_regions.return_value = ["us-east-1"]
        return session

    def test_warns_when_search_hits_the_1000_result_limit(self):
        from structlog.testing import capture_logs

        with capture_logs() as logs:
            list_resources(self._session(1000))

        events = [e for e in logs if e["event"] == "resource_explorer_search_limit"]
        assert len(events) == 1
        assert events[0]["log_level"] == "warning"
        assert events[0]["results"] == 1000

    def test_no_warning_below_the_limit(self):
        from structlog.testing import capture_logs

        with capture_logs() as logs:
            list_resources(self._session(999))

        assert not [e for e in logs if e["event"] == "resource_explorer_search_limit"]


class TestPerRegionDiscovery:
    """A full first query (1000 results) falls back to one query per region."""

    REGIONS = ["us-east-1", "eu-west-1"]

    def _session(self, per_query, regions=None):
        """per_query maps a QueryString to the list of raw resources it returns."""
        client = MagicMock()
        queries = []

        def paginate(QueryString, **kw):
            queries.append(QueryString)
            items = per_query.get(QueryString, [])
            pages = range(0, len(items), 500)
            return [{"Resources": items[i : i + 500]} for i in pages]

        client.get_paginator.return_value.paginate.side_effect = paginate
        session = MagicMock()
        session.client.return_value = client
        session.get_available_regions.return_value = regions or self.REGIONS
        return session, queries

    def _raw(self, region, n, tag):
        return [
            _make_raw_resource(
                arn=f"arn:aws:ec2:{region}:1:volume/{tag}-{i}", region=region
            )
            for i in range(n)
        ]

    def test_small_account_uses_one_query_and_is_complete(self):
        session, queries = self._session({"*": self._raw("us-east-1", 10, "a")})

        resources, complete = list_resources_with_status(session)

        assert queries == ["*"]
        assert len(resources) == 10 and complete is True

    def test_full_first_query_falls_back_to_one_query_per_region(self):
        first = self._raw("us-east-1", 1000, "a")
        session, queries = self._session(
            {
                "*": first,
                "region:us-east-1": first[:700],
                "region:eu-west-1": self._raw("eu-west-1", 600, "b"),
                "region:global": self._raw("global", 5, "g"),
            }
        )

        resources, complete = list_resources_with_status(session)

        assert queries[0] == "*"
        assert set(queries[1:]) == {
            "region:us-east-1",
            "region:eu-west-1",
            "region:global",
        }
        # union with the first (truncated) query: 1000 + 600 + 5, nothing double counted
        assert len(resources) == 1000 + 600 + 5
        assert complete is True

    def test_a_region_that_still_hits_the_limit_marks_discovery_incomplete(self):
        from structlog.testing import capture_logs

        full = self._raw("us-east-1", 1000, "a")
        session, _ = self._session(
            {"*": full, "region:us-east-1": full, "region:eu-west-1": []}
        )

        with capture_logs() as logs:
            resources, complete = list_resources_with_status(session)

        assert complete is False
        assert len(resources) == 1000
        assert [e for e in logs if e["event"] == "resource_explorer_region_limit"]

    def test_results_are_deduplicated_by_arn_across_queries(self):
        first = self._raw("us-east-1", 1000, "a")
        session, _ = self._session(
            {"*": first, "region:us-east-1": first[:10], "region:eu-west-1": first[:5]}
        )

        resources, _ = list_resources_with_status(session)

        assert len({r.resource_id for r in resources}) == len(resources) == 1000

    def test_ignored_regions_are_not_queried(self):
        first = self._raw("us-east-1", 1000, "a")
        session, queries = self._session({"*": first, "region:us-east-1": first[:3]})

        list_resources_with_status(session, ignore_regions=["eu-west-1", "global"])

        assert "region:eu-west-1" not in queries
        assert "region:global" not in queries

    def test_list_resources_still_returns_a_plain_list(self):
        session, _ = self._session({"*": self._raw("us-east-1", 3, "a")})

        assert len(list_resources(session)) == 3


class TestFreeConfigObjectsAreCountedNotHidden:
    def _session(self, raws):
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = [{"Resources": raws}]
        session = MagicMock()
        session.client.return_value = client
        session.get_available_regions.return_value = []
        return session

    def test_skipped_types_are_reported_by_type(self):
        raws = [
            _make_raw_resource(
                arn="arn:aws:ec2:r:1:volume/v1", resource_type="ec2:volume"
            ),
            _make_raw_resource(
                arn="arn:aws:ec2:r:1:subnet/s1", resource_type="ec2:subnet"
            ),
            _make_raw_resource(
                arn="arn:aws:ec2:r:1:subnet/s2", resource_type="ec2:subnet"
            ),
            _make_raw_resource(arn="arn:aws:iam::1:role/r", resource_type="iam:role"),
        ]

        found = discover(self._session(raws))

        assert [r.native_type for r in found.resources] == ["ec2:volume"]
        assert found.filtered_by_type == {"ec2:subnet": 2, "iam:role": 1}
        assert found.complete is True

    def test_ignored_regions_are_not_counted_as_skipped(self):
        raws = [
            _make_raw_resource(
                arn="arn:aws:ec2:eu:1:subnet/s1",
                resource_type="ec2:subnet",
                region="eu-west-1",
            )
        ]

        found = discover(self._session(raws), ignore_regions=["eu-west-1"])

        assert found.filtered == {}
