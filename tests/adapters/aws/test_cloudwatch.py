from unittest.mock import MagicMock, patch

from adapters.aws.cloudwatch import _dimension_value, _region_from_arn, _enrich_instance_details, get_metrics


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
        arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/app/my-alb/abc123"
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
        mock_client.get_metric_data.return_value = {"MetricDataResults": []}
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


import pytest


class TestEnrichInstanceDetails:
    """_enrich_instance_details injects instance size metadata into the metrics dict."""

    def _make_session(self, client_mock: MagicMock) -> MagicMock:
        session = MagicMock()
        session.client.return_value = client_mock
        return session

    def test_ec2_injects_instance_type_and_vcpus(self):
        ec2_client = MagicMock()
        ec2_client.describe_instances.return_value = {
            "Reservations": [{
                "Instances": [{
                    "InstanceType": "m5.4xlarge",
                    "CpuOptions": {"CoreCount": 8, "ThreadsPerCore": 2},
                }]
            }]
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
            "DBInstances": [{
                "DBInstanceClass": "db.r5.4xlarge",
                "Engine": "postgres",
                "EngineVersion": "14.7",
                "AllocatedStorage": 500,
                "MultiAZ": True,
            }]
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
            "CacheClusters": [{
                "CacheNodeType": "cache.r6g.xlarge",
                "NumCacheNodes": 3,
                "Engine": "redis",
                "EngineVersion": "7.0.5",
            }]
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
