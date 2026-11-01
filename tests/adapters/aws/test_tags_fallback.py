from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from adapters.aws.adapter import AWSAdapter
from adapters.aws.resource_explorer import Discovery
from adapters.aws.tags import fetch_tags
from adapters.base import Resource


def _res(arn, region="us-east-1", tags=None):
    return Resource(arn, "AWS::EC2::Volume", "aws", region, tags=tags or {})


def _tagging(by_arn=None, error=None):
    client = MagicMock()
    calls = []

    def get_resources(ResourceARNList, **kw):
        calls.append(list(ResourceARNList))
        if error:
            raise error
        return {
            "ResourceTagMappingList": [
                {
                    "ResourceARN": arn,
                    "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
                }
                for arn, tags in (by_arn or {}).items()
                if arn in ResourceARNList
            ]
        }

    client.get_resources.side_effect = get_resources
    client.calls = calls
    return client


def _session(by_region):
    session = MagicMock()
    session.client.side_effect = lambda name, region_name=None, **kw: by_region[
        region_name
    ]
    return session


def test_tags_are_fetched_per_region_in_chunks_of_100():
    arns = [f"arn:aws:ec2:us-east-1:1:volume/vol-{i}" for i in range(230)]
    client = _tagging({arns[0]: {"Name": "data", "env": "prod"}})

    tags = fetch_tags(_session({"us-east-1": client}), [_res(a) for a in arns])

    assert [len(c) for c in client.calls] == [100, 100, 30]
    assert tags[arns[0]] == {"Name": "data", "env": "prod"}
    assert arns[1] not in tags


def test_regions_are_queried_separately():
    east = _tagging({"arn:e": {"a": "1"}})
    west = _tagging({"arn:w": {"b": "2"}})
    resources = [_res("arn:e", "us-east-1"), _res("arn:w", "eu-west-1")]

    tags = fetch_tags(_session({"us-east-1": east, "eu-west-1": west}), resources)

    assert tags == {"arn:e": {"a": "1"}, "arn:w": {"b": "2"}}


def test_a_denied_call_returns_nothing_instead_of_raising():
    denied = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "GetResources"
    )

    assert (
        fetch_tags(_session({"us-east-1": _tagging(error=denied)}), [_res("arn:e")])
        is None
    )


def test_global_resources_use_the_aggregator_region():
    client = _tagging({"arn:g": {"k": "v"}})
    resources = [_res("arn:g", "global")]

    tags = fetch_tags(
        _session({"us-east-1": client}), resources, default_region="us-east-1"
    )

    assert tags == {"arn:g": {"k": "v"}}


class TestAdapterFallback:
    def _adapter(self, tagging_result, resources):
        adapter = AWSAdapter(MagicMock(), aggregator_region="us-east-1")
        patches = (
            patch(
                "adapters.aws.adapter.resource_explorer.discover",
                return_value=Discovery(resources, True),
            ),
            patch("adapters.aws.adapter.fetch_tags", return_value=tagging_result),
        )
        return adapter, patches

    def test_untagged_inventory_triggers_the_fallback_and_applies_tags(self):
        res = [_res("arn:a"), _res("arn:b")]
        adapter, (p1, p2) = self._adapter(
            {"arn:a": {"Name": "web", "env": "prod"}}, res
        )

        with p1, p2:
            out = adapter.list_resources()

        by = {r.resource_id: r for r in out}
        assert by["arn:a"].tags == {"Name": "web", "env": "prod"}
        assert by["arn:a"].name == "web"
        assert by["arn:b"].tags == {}
        assert adapter.tags_source == "tagging_api"

    def test_an_inventory_that_already_has_tags_makes_no_extra_calls(self):
        res = [_res("arn:a", tags={"env": "prod"}), _res("arn:b")]
        adapter, (p1, p2) = self._adapter({}, res)

        with p1, p2 as fetch:
            adapter.list_resources()

        fetch.assert_not_called()
        assert adapter.tags_source == "resource_explorer"

    def test_a_failed_fallback_is_reported_as_unavailable(self):
        adapter, (p1, p2) = self._adapter(None, [_res("arn:a")])

        with p1, p2:
            adapter.list_resources()

        assert adapter.tags_source == "unavailable"

    def test_nothing_discovered_means_nothing_to_tag(self):
        adapter, (p1, p2) = self._adapter({}, [])

        with p1, p2 as fetch:
            adapter.list_resources()

        fetch.assert_not_called()
