from unittest.mock import MagicMock

import pytest

from adapters.aws.cloudwatch import (
    _dimension_value,
    _enrich_instance_details,
    _region_from_arn,
    get_metrics,
)


def _make_mock_session(metric_results):
    mock_client = MagicMock()
    mock_client.get_metric_data.return_value = {"MetricDataResults": metric_results}
    mock_session = MagicMock()
    mock_session.client.return_value = mock_client
    return mock_session, mock_client


class TestRegionAndDimensionHelpers:
    def test_region_from_ec2_arn(self):
        arn = "arn:aws:ec2:us-west-2:123:instance/i-0abc"
        assert _region_from_arn(arn) == "us-west-2"

    def test_region_defaults_to_us_east_1(self):
        assert _region_from_arn("invalid") == "us-east-1"

    def test_dimension_ec2_instance(self):
        arn = "arn:aws:ec2:us-east-1:123:instance/i-0abc123"
        assert _dimension_value(arn, "AWS::EC2::Instance") == "i-0abc123"

    def test_dimension_rds_instance(self):
        arn = "arn:aws:rds:us-east-1:123:db:my-database"
        assert _dimension_value(arn, "AWS::RDS::DBInstance") == "my-database"

    def test_dimension_nat_gateway(self):
        arn = "arn:aws:ec2:us-east-1:123:natgateway/nat-0abc123"
        assert _dimension_value(arn, "AWS::EC2::NatGateway") == "nat-0abc123"

    def test_dimension_lambda_function(self):
        arn = "arn:aws:lambda:us-east-1:123:function:my-fn"
        assert _dimension_value(arn, "AWS::Lambda::Function") == "my-fn"

    def test_dimension_alb(self):
        arn = (
            "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
        )
        result = _dimension_value(arn, "AWS::ElasticLoadBalancingV2::LoadBalancer")
        assert result == "app/my-alb/abc123"

    def test_dimension_ebs_volume(self):
        arn = "arn:aws:ec2:us-east-1:123:volume/vol-0abc123"
        assert _dimension_value(arn, "AWS::EC2::Volume") == "vol-0abc123"


class TestGetMetrics:
    def test_returns_averaged_cpu_for_ec2(self):
        results = [
            {"Id": "m0", "Values": [1.2, 0.8, 1.5], "Timestamps": []},
            {"Id": "m1", "Values": [1024, 2048, 512], "Timestamps": []},
            {"Id": "m2", "Values": [512, 256, 768], "Timestamps": []},
        ]
        session, _ = _make_mock_session(results)
        summary = get_metrics(
            session,
            resource_id="arn:aws:ec2:us-east-1:123:instance/i-0abc",
            resource_type="AWS::EC2::Instance",
            days=14,
        )

        assert summary.has_data is True
        assert summary.metrics["CPUUtilization"] == pytest.approx(1.1667, rel=1e-2)
        assert summary.metrics["NetworkOut"] == 3584.0

    def test_returns_has_data_false_for_unknown_type(self):
        mock_client = MagicMock()
        mock_client.list_metrics.return_value = {"Metrics": []}
        session = MagicMock()
        session.client.return_value = mock_client
        summary = get_metrics(
            session,
            resource_id="arn:aws:unknown:us-east-1:123:widget/my-widget",
            resource_type="AWS::Unknown::Widget",
            days=14,
        )
        assert summary.has_data is False
        assert summary.metrics == {}

    def test_returns_has_data_false_when_no_cloudwatch_data(self):
        results = [
            {"Id": "m0", "Values": [], "Timestamps": []},
            {"Id": "m1", "Values": [], "Timestamps": []},
            {"Id": "m2", "Values": [], "Timestamps": []},
        ]
        session, _ = _make_mock_session(results)
        summary = get_metrics(
            session,
            resource_id="arn:aws:ec2:us-east-1:123:instance/i-0abc",
            resource_type="AWS::EC2::Instance",
            days=14,
        )
        assert summary.has_data is False
        assert summary.metrics["CPUUtilization"] is None

    def test_handles_cloudwatch_error_gracefully(self):
        from botocore.exceptions import ClientError

        mock_client = MagicMock()
        mock_client.get_metric_data.side_effect = ClientError(
            {"Error": {"Code": "InvalidParameterCombination", "Message": "err"}},
            "GetMetricData",
        )
        mock_session = MagicMock()
        mock_session.client.return_value = mock_client

        summary = get_metrics(
            mock_session,
            resource_id="arn:aws:ec2:us-east-1:123:instance/i-0abc",
            resource_type="AWS::EC2::Instance",
        )
        assert summary.has_data is False


class TestMetricStatus:
    ARN = "arn:aws:ec2:us-east-1:123:instance/i-0abc"
    EC2 = "AWS::EC2::Instance"

    def test_data_present_is_ok(self):
        results = [{"Id": f"m{i}", "Values": [1.0]} for i in range(3)]
        session, _ = _make_mock_session(results)
        summary = get_metrics(session, self.ARN, self.EC2, days=14)
        assert summary.status == "ok"
        assert "data_note" not in summary.to_dict()

    def test_no_datapoints_is_no_data(self):
        results = [{"Id": f"m{i}", "Values": []} for i in range(3)]
        session, _ = _make_mock_session(results)
        summary = get_metrics(session, self.ARN, self.EC2, days=14)
        assert summary.status == "no_data"
        assert "unavailable" in summary.to_dict()["data_note"]

    def test_access_denied_is_error_not_no_data(self):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.get_metric_data.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetMetricData"
        )
        session = MagicMock()
        session.client.return_value = client

        summary = get_metrics(session, self.ARN, self.EC2, days=14)

        assert summary.has_data is False
        assert summary.status == "error"
        assert "AccessDenied" in summary.error
        assert "AccessDenied" in summary.to_dict()["data_note"]


class TestDiscoveryThrottling:
    ARN = "arn:aws:unknown:us-east-1:123:widget/orders"
    TYPE = "AWS::Unknown::Widget"

    @staticmethod
    def _throttle():
        from botocore.exceptions import ClientError

        return ClientError(
            {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}},
            "ListMetrics",
        )

    @staticmethod
    def _session(client):
        session = MagicMock()
        session.client.return_value = client
        return session

    def test_list_metrics_throttle_is_retried_and_recovers(self, monkeypatch):
        monkeypatch.setattr("adapters.aws.retry.time.sleep", lambda _s: None)
        client = MagicMock()
        client.list_metrics.side_effect = [
            self._throttle(),
            {
                "Metrics": [
                    {
                        "Namespace": "AWS/Kinesis",
                        "MetricName": "IncomingRecords",
                        "Dimensions": [{"Name": "StreamName", "Value": "orders"}],
                    }
                ]
            },
        ]
        client.get_metric_data.return_value = {
            "MetricDataResults": [{"Id": "m0", "Values": [5.0]}]
        }

        summary = get_metrics(self._session(client), self.ARN, self.TYPE, days=14)

        assert client.list_metrics.call_count == 2
        assert summary.status == "ok"

    def test_persistent_throttle_is_an_error_not_no_data(self, monkeypatch):
        monkeypatch.setattr("adapters.aws.retry.time.sleep", lambda _s: None)
        client = MagicMock()
        client.list_metrics.side_effect = self._throttle()

        summary = get_metrics(self._session(client), self.ARN, self.TYPE, days=14)

        assert summary.status == "error"
        assert "Throttling" in summary.error

    def test_list_metrics_follows_next_token(self, monkeypatch):
        monkeypatch.setattr("adapters.aws.retry.time.sleep", lambda _s: None)
        client = MagicMock()
        client.list_metrics.side_effect = [
            {"Metrics": [], "NextToken": "t1"},
            {
                "Metrics": [
                    {
                        "Namespace": "AWS/Kinesis",
                        "MetricName": "IncomingBytes",
                        "Dimensions": [{"Name": "StreamName", "Value": "orders"}],
                    }
                ]
            },
        ]
        client.get_metric_data.return_value = {
            "MetricDataResults": [{"Id": "m0", "Values": [1.0]}]
        }

        summary = get_metrics(self._session(client), self.ARN, self.TYPE, days=14)

        assert client.list_metrics.call_args_list[1].kwargs["NextToken"] == "t1"
        assert summary.status == "ok"


class TestListMetricsCache:
    TYPE = "AWS::Unknown::Widget"

    @staticmethod
    def _arn(name, region="us-east-1"):
        return f"arn:aws:unknown:{region}:123:widget/{name}"

    @staticmethod
    def _metric(name):
        return {
            "Namespace": "Custom/Widget",
            "MetricName": "Requests",
            "Dimensions": [{"Name": "WidgetName", "Value": name}],
        }

    @staticmethod
    def _session(client):
        session = MagicMock()
        session.client.return_value = client
        return session

    @staticmethod
    def _client(metrics):
        client = MagicMock()
        client.list_metrics.return_value = {"Metrics": metrics}
        client.get_metric_data.return_value = {
            "MetricDataResults": [{"Id": "m0", "Values": [3.0]}]
        }
        return client

    def test_resources_in_one_region_share_one_listing(self):
        client = self._client([self._metric("a"), self._metric("b")])
        session = self._session(client)

        first = get_metrics(session, self._arn("a"), self.TYPE, days=14)
        second = get_metrics(session, self._arn("b"), self.TYPE, days=14)

        assert client.list_metrics.call_count == 1
        assert first.status == "ok" and second.status == "ok"

    def test_each_region_is_listed_once(self):
        client = self._client([self._metric("a")])
        session = self._session(client)

        get_metrics(session, self._arn("a", "us-east-1"), self.TYPE, days=14)
        get_metrics(session, self._arn("a", "eu-west-1"), self.TYPE, days=14)
        get_metrics(session, self._arn("a", "eu-west-1"), self.TYPE, days=14)

        assert client.list_metrics.call_count == 2

    def test_a_new_session_starts_with_an_empty_cache(self):
        client = self._client([self._metric("a")])

        get_metrics(self._session(client), self._arn("a"), self.TYPE, days=14)
        get_metrics(self._session(client), self._arn("a"), self.TYPE, days=14)

        assert client.list_metrics.call_count == 2

    def test_a_failed_listing_is_not_retried_for_every_resource(self, monkeypatch):
        from botocore.exceptions import ClientError

        monkeypatch.setattr("adapters.aws.retry.time.sleep", lambda _s: None)
        client = self._client([])
        client.list_metrics.side_effect = ClientError(
            {"Error": {"Code": "Throttling", "Message": "Rate exceeded"}},
            "ListMetrics",
        )
        session = self._session(client)

        first = get_metrics(session, self._arn("a"), self.TYPE, days=14)
        calls_after_first = client.list_metrics.call_count
        second = get_metrics(session, self._arn("b"), self.TYPE, days=14)

        assert client.list_metrics.call_count == calls_after_first
        assert first.status == "error" and second.status == "error"
        assert "Throttling" in second.error
        assert second.metrics == {}

    def test_concurrent_resources_still_list_a_region_once(self):
        import time
        from concurrent.futures import ThreadPoolExecutor

        client = self._client([self._metric(f"w{i}") for i in range(8)])
        original = client.list_metrics.return_value

        def slow(**_kw):
            time.sleep(0.05)
            return original

        client.list_metrics.side_effect = slow
        session = self._session(client)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda i: get_metrics(session, self._arn(f"w{i}"), self.TYPE, 14),
                    range(8),
                )
            )

        assert client.list_metrics.call_count == 1
        assert all(r.status == "ok" for r in results)


class TestEnrichInstanceDetails:
    """_enrich_instance_details injects instance size metadata into the metrics dict."""

    def _make_session(self, client_mock: MagicMock) -> MagicMock:
        session = MagicMock()
        session.client.return_value = client_mock
        return session

    def test_ec2_injects_instance_type_and_vcpus(self):
        ec2_client = MagicMock()
        ec2_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceType": "m5.4xlarge",
                            "CpuOptions": {"CoreCount": 8, "ThreadsPerCore": 2},
                        }
                    ]
                }
            ]
        }
        session = self._make_session(ec2_client)
        metrics: dict = {}
        _enrich_instance_details(
            session,
            "arn:aws:ec2:us-east-1:123:instance/i-0abc",
            "AWS::EC2::Instance",
            metrics,
        )
        assert metrics["instance_type"] == "m5.4xlarge"
        assert metrics["vcpus"] == 16

    def test_rds_injects_instance_class_and_engine(self):
        rds_client = MagicMock()
        rds_client.describe_db_instances.return_value = {
            "DBInstances": [
                {
                    "DBInstanceClass": "db.r5.4xlarge",
                    "Engine": "postgres",
                    "EngineVersion": "14.7",
                    "AllocatedStorage": 500,
                    "MultiAZ": True,
                }
            ]
        }
        session = self._make_session(rds_client)
        metrics: dict = {}
        _enrich_instance_details(
            session,
            "arn:aws:rds:us-east-1:123:db:my-db",
            "AWS::RDS::DBInstance",
            metrics,
        )
        assert metrics["instance_type"] == "db.r5.4xlarge"
        assert metrics["engine"] == "postgres 14.7"
        assert metrics["storage_gb"] == 500
        assert metrics["multi_az"] is True

    def test_elasticache_injects_node_type(self):
        ec_client = MagicMock()
        ec_client.describe_cache_clusters.return_value = {
            "CacheClusters": [
                {
                    "CacheNodeType": "cache.r6g.xlarge",
                    "NumCacheNodes": 3,
                    "Engine": "redis",
                    "EngineVersion": "7.0.5",
                }
            ]
        }
        session = self._make_session(ec_client)
        metrics: dict = {}
        _enrich_instance_details(
            session,
            "arn:aws:elasticache:us-east-1:123:cluster:my-cluster",
            "AWS::ElastiCache::CacheCluster",
            metrics,
        )
        assert metrics["instance_type"] == "cache.r6g.xlarge"
        assert metrics["num_cache_nodes"] == 3

    def test_lambda_injects_memory_and_runtime(self):
        lam_client = MagicMock()
        lam_client.get_function_configuration.return_value = {
            "MemorySize": 1024,
            "EphemeralStorage": {"Size": 512},
            "Runtime": "python3.13",
        }
        session = self._make_session(lam_client)
        metrics: dict = {}
        _enrich_instance_details(
            session,
            "arn:aws:lambda:us-east-1:123:function:my-fn",
            "AWS::Lambda::Function",
            metrics,
        )
        assert metrics["memory_mb"] == 1024
        assert metrics["ephemeral_storage_mb"] == 512
        assert metrics["runtime"] == "python3.13"

    def test_client_error_is_silently_ignored(self):
        from botocore.exceptions import ClientError

        ec2_client = MagicMock()
        ec2_client.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceID", "Message": "not found"}},
            "DescribeInstances",
        )
        session = self._make_session(ec2_client)
        metrics: dict = {"CPUUtilization": 0.5}
        # Should not raise; existing metrics must be untouched
        _enrich_instance_details(
            session,
            "arn:aws:ec2:us-east-1:123:instance/i-gone",
            "AWS::EC2::Instance",
            metrics,
        )
        assert metrics["CPUUtilization"] == 0.5
        assert "instance_type" not in metrics

    def test_unsupported_resource_type_leaves_metrics_unchanged(self):
        session = MagicMock()
        metrics: dict = {"RequestCount": 42.0}
        _enrich_instance_details(
            session,
            "arn:aws:sqs:us-east-1:123:queue/my-queue",
            "AWS::SQS::Queue",
            metrics,
        )
        assert metrics == {"RequestCount": 42.0}
        session.client.assert_not_called()
