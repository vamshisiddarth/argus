import pytest

from core.registry.models import MetricSpec, ResourceTypeSpec
from core.registry.registry import ResourceRegistry


@pytest.fixture()
def registry() -> ResourceRegistry:
    r = ResourceRegistry()
    r.register(
        ResourceTypeSpec(
            type_id="AWS::EC2::Instance",
            cloud="aws",
            display_name="EC2 Instance",
            service="Compute",
            metrics=(
                MetricSpec("CPUUtilization", "AWS/EC2", "Average", "InstanceId"),
                MetricSpec("NetworkOut", "AWS/EC2", "Sum", "InstanceId"),
            ),
            typical_monthly_cost_usd=50.0,
        )
    )
    r.register(
        ResourceTypeSpec(
            type_id="AWS::RDS::DBInstance",
            cloud="aws",
            display_name="RDS Instance",
            service="Database",
            metrics=(
                MetricSpec("CPUUtilization", "AWS/RDS", "Average", "DBInstanceIdentifier"),
                MetricSpec("DatabaseConnections", "AWS/RDS", "Average", "DBInstanceIdentifier"),
            ),
        )
    )
    r.register(
        ResourceTypeSpec(
            type_id="compute.googleapis.com/Instance",
            cloud="gcp",
            display_name="GCE Instance",
            service="Compute",
        )
    )
    return r


class TestResourceTypeSpec:
    def test_immutable(self) -> None:
        spec = ResourceTypeSpec(
            type_id="AWS::EC2::Instance",
            cloud="aws",
            display_name="EC2 Instance",
            service="Compute",
        )
        with pytest.raises(Exception):
            spec.type_id = "other"  # type: ignore[misc]

    def test_metrics_default_empty(self) -> None:
        spec = ResourceTypeSpec(
            type_id="AWS::EC2::Instance",
            cloud="aws",
            display_name="EC2 Instance",
            service="Compute",
        )
        assert spec.metrics == ()

    def test_optional_fields_default_none(self) -> None:
        spec = ResourceTypeSpec(
            type_id="t",
            cloud="aws",
            display_name="T",
            service="S",
        )
        assert spec.typical_monthly_cost_usd is None
        assert spec.docs_url is None


class TestMetricSpec:
    def test_fields(self) -> None:
        m = MetricSpec("CPUUtilization", "AWS/EC2", "Average", "InstanceId")
        assert m.name == "CPUUtilization"
        assert m.namespace == "AWS/EC2"
        assert m.stat == "Average"
        assert m.dimension_key == "InstanceId"

    def test_immutable(self) -> None:
        m = MetricSpec("CPU", "ns", "Average", "dim")
        with pytest.raises(Exception):
            m.name = "other"  # type: ignore[misc]


class TestResourceRegistry:
    def test_get_known_type(self, registry: ResourceRegistry) -> None:
        spec = registry.get("AWS::EC2::Instance")
        assert spec is not None
        assert spec.display_name == "EC2 Instance"

    def test_get_unknown_returns_none(self, registry: ResourceRegistry) -> None:
        assert registry.get("AWS::Unknown::Type") is None

    def test_display_name_known(self, registry: ResourceRegistry) -> None:
        assert registry.display_name("AWS::RDS::DBInstance") == "RDS Instance"

    def test_display_name_unknown_falls_back_to_type_id(self, registry: ResourceRegistry) -> None:
        assert registry.display_name("AWS::Unknown::Type") == "AWS::Unknown::Type"

    def test_all_for_cloud_aws(self, registry: ResourceRegistry) -> None:
        aws = registry.all_for_cloud("aws")
        assert len(aws) == 2
        assert all(s.cloud == "aws" for s in aws)

    def test_all_for_cloud_gcp(self, registry: ResourceRegistry) -> None:
        gcp = registry.all_for_cloud("gcp")
        assert len(gcp) == 1
        assert gcp[0].type_id == "compute.googleapis.com/Instance"

    def test_all_for_cloud_azure_empty(self, registry: ResourceRegistry) -> None:
        assert registry.all_for_cloud("azure") == []

    def test_all_type_ids(self, registry: ResourceRegistry) -> None:
        ids = registry.all_type_ids()
        assert "AWS::EC2::Instance" in ids
        assert "AWS::RDS::DBInstance" in ids
        assert "compute.googleapis.com/Instance" in ids

    def test_len(self, registry: ResourceRegistry) -> None:
        assert len(registry) == 3

    def test_register_overwrites(self, registry: ResourceRegistry) -> None:
        registry.register(
            ResourceTypeSpec(
                type_id="AWS::EC2::Instance",
                cloud="aws",
                display_name="EC2 (updated)",
                service="Compute",
            )
        )
        assert registry.display_name("AWS::EC2::Instance") == "EC2 (updated)"
        assert len(registry) == 3  # no duplicate

    def test_metrics_accessible(self, registry: ResourceRegistry) -> None:
        spec = registry.get("AWS::EC2::Instance")
        assert spec is not None
        assert len(spec.metrics) == 2
        assert spec.metrics[0].name == "CPUUtilization"

    def test_empty_registry(self) -> None:
        r = ResourceRegistry()
        assert len(r) == 0
        assert r.get("anything") is None
        assert r.all_for_cloud("aws") == []
        assert r.all_type_ids() == []
