import json
from unittest.mock import MagicMock, patch

import pytest

from adapters.aws.resource_explorer import _parse_tags, _parse_resource, _is_billable, list_resources
from adapters.base import Resource


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
        "Properties": [
            {"Name": "tags", "Data": json.dumps(tag_list)}
        ],
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
            {"Name": "tags", "Data": json.dumps([{"Key": "Name", "Value": "web-01"}, {"Key": "Env", "Value": "prod"}])}
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
        assert result.resource_id == "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123"
        assert result.resource_type == "AWS::EC2::Instance"
        assert result.cloud == "aws"
        assert result.region == "us-east-1"
        assert result.name == "my-server"
        assert result.tags == {"Name": "my-server", "Env": "staging"}

    def test_returns_none_for_missing_arn(self):
        assert _parse_resource({"ResourceType": "AWS::EC2::Instance", "Region": "us-east-1"}) is None

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
            {"Resources": [_make_raw_resource(
                arn="arn:aws:ec2:us-west-2:123:instance/i-0def456",
                region="us-west-2",
            )]},
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
