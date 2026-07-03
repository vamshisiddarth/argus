"""
Phase 4 integration tests for the Resource Registry.

These tests validate:
- get_registry() factory and singleton behaviour
- Data quality of all 114 registered resource types
- _metrics_for() adapter helpers correctly convert registry specs
- Report generator uses registry display names
"""
from __future__ import annotations

import pytest

from core.registry import ResourceRegistry, actions_section, get_registry
from core.registry.aws import AWS_RESOURCE_TYPES
from core.registry.azure import AZURE_RESOURCE_TYPES
from core.registry.gcp import GCP_RESOURCE_TYPES
from core.registry.models import MetricSpec, ResourceTypeSpec
from core.registry.registry import _VALID_ACTIONS


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------
class TestGetRegistry:
    def test_returns_registry_instance(self):
        r = get_registry()
        assert isinstance(r, ResourceRegistry)

    def test_singleton_same_object(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_total_resource_count(self):
        assert len(get_registry()) == 114

    def test_aws_count(self):
        assert len(get_registry().all_for_cloud("aws")) == 43

    def test_gcp_count(self):
        assert len(get_registry().all_for_cloud("gcp")) == 31

    def test_azure_count(self):
        assert len(get_registry().all_for_cloud("azure")) == 40


# ---------------------------------------------------------------------------
# AWS data quality
# ---------------------------------------------------------------------------
class TestAWSDataQuality:
    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_cloud_field(self, spec: ResourceTypeSpec):
        assert spec.cloud == "aws"

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_type_id_prefix(self, spec: ResourceTypeSpec):
        assert spec.type_id.startswith("AWS::")

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_has_display_name(self, spec: ResourceTypeSpec):
        assert spec.display_name

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_has_metrics(self, spec: ResourceTypeSpec):
        assert len(spec.metrics) >= 1

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_metric_stat_is_valid(self, spec: ResourceTypeSpec):
        valid = {"Average", "Sum", "Maximum", "Minimum", "mean", "sum"}
        for m in spec.metrics:
            assert m.stat in valid, f"{spec.type_id}: invalid stat '{m.stat}'"

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_metric_has_namespace(self, spec: ResourceTypeSpec):
        for m in spec.metrics:
            assert m.namespace, f"{spec.type_id}: empty namespace"

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_metric_has_dimension_key(self, spec: ResourceTypeSpec):
        for m in spec.metrics:
            assert m.dimension_key, f"{spec.type_id}: empty dimension_key"

    def test_ec2_cpu_metric(self):
        spec = get_registry().get("AWS::EC2::Instance")
        assert spec is not None
        names = [m.name for m in spec.metrics]
        assert "CPUUtilization" in names

    def test_lambda_invocations_metric(self):
        spec = get_registry().get("AWS::Lambda::Function")
        assert spec is not None
        names = [m.name for m in spec.metrics]
        assert "Invocations" in names

    def test_rds_display_name(self):
        assert get_registry().display_name("AWS::RDS::DBInstance") == "RDS Instance"

    def test_no_duplicate_type_ids(self):
        ids = [s.type_id for s in AWS_RESOURCE_TYPES]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_actions_are_valid_vocab(self, spec: ResourceTypeSpec):
        invalid = set(spec.actions) - _VALID_ACTIONS
        assert not invalid, f"{spec.type_id}: unknown actions {invalid}"

    @pytest.mark.parametrize("spec", AWS_RESOURCE_TYPES)
    def test_has_at_least_one_action(self, spec: ResourceTypeSpec):
        assert len(spec.actions) >= 1, f"{spec.type_id} has no actions"

    def test_ec2_has_resize_and_stop(self):
        spec = get_registry().get("AWS::EC2::Instance")
        assert spec is not None
        assert "resize" in spec.actions
        assert "stop" in spec.actions
        assert "convert_spot" in spec.actions

    def test_all_for_action_resize_includes_ec2_and_rds(self):
        resizable = get_registry().all_for_action("resize")
        type_ids = [s.type_id for s in resizable]
        assert "AWS::EC2::Instance" in type_ids
        assert "AWS::RDS::DBInstance" in type_ids

    def test_all_for_action_delete_includes_all_clouds(self):
        deletable = get_registry().all_for_action("delete")
        clouds = {s.cloud for s in deletable}
        assert clouds == {"aws", "gcp", "azure"}


# ---------------------------------------------------------------------------
# GCP data quality
# ---------------------------------------------------------------------------
class TestGCPDataQuality:
    @pytest.mark.parametrize("spec", GCP_RESOURCE_TYPES)
    def test_cloud_field(self, spec: ResourceTypeSpec):
        assert spec.cloud == "gcp"

    @pytest.mark.parametrize("spec", GCP_RESOURCE_TYPES)
    def test_has_display_name(self, spec: ResourceTypeSpec):
        assert spec.display_name

    @pytest.mark.parametrize("spec", GCP_RESOURCE_TYPES)
    def test_has_metrics(self, spec: ResourceTypeSpec):
        assert len(spec.metrics) >= 1

    @pytest.mark.parametrize("spec", GCP_RESOURCE_TYPES)
    def test_metric_stat_is_valid(self, spec: ResourceTypeSpec):
        valid = {"mean", "sum", "Average", "Sum"}
        for m in spec.metrics:
            assert m.stat in valid, f"{spec.type_id}: invalid stat '{m.stat}'"

    def test_gce_instance_in_registry(self):
        spec = get_registry().get("compute.googleapis.com/Instance")
        assert spec is not None
        assert spec.display_name == "GCE Instance"

    def test_cloud_sql_display_name(self):
        assert get_registry().display_name("sqladmin.googleapis.com/Instance") == "Cloud SQL Instance"

    def test_no_duplicate_type_ids(self):
        ids = [s.type_id for s in GCP_RESOURCE_TYPES]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("spec", GCP_RESOURCE_TYPES)
    def test_actions_are_valid_vocab(self, spec: ResourceTypeSpec):
        invalid = set(spec.actions) - _VALID_ACTIONS
        assert not invalid, f"{spec.type_id}: unknown actions {invalid}"

    @pytest.mark.parametrize("spec", GCP_RESOURCE_TYPES)
    def test_has_at_least_one_action(self, spec: ResourceTypeSpec):
        assert len(spec.actions) >= 1, f"{spec.type_id} has no actions"

    def test_gce_has_stop_and_convert_spot(self):
        spec = get_registry().get("compute.googleapis.com/Instance")
        assert spec is not None
        assert "stop" in spec.actions
        assert "convert_spot" in spec.actions


# ---------------------------------------------------------------------------
# Azure data quality
# ---------------------------------------------------------------------------
class TestAzureDataQuality:
    @pytest.mark.parametrize("spec", AZURE_RESOURCE_TYPES)
    def test_cloud_field(self, spec: ResourceTypeSpec):
        assert spec.cloud == "azure"

    @pytest.mark.parametrize("spec", AZURE_RESOURCE_TYPES)
    def test_has_display_name(self, spec: ResourceTypeSpec):
        assert spec.display_name

    @pytest.mark.parametrize("spec", AZURE_RESOURCE_TYPES)
    def test_has_metrics(self, spec: ResourceTypeSpec):
        assert len(spec.metrics) >= 1

    def test_vm_in_registry(self):
        spec = get_registry().get("microsoft.compute/virtualmachines")
        assert spec is not None
        names = [m.name for m in spec.metrics]
        assert "Percentage CPU" in names

    def test_no_duplicate_type_ids(self):
        ids = [s.type_id for s in AZURE_RESOURCE_TYPES]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("spec", AZURE_RESOURCE_TYPES)
    def test_actions_are_valid_vocab(self, spec: ResourceTypeSpec):
        invalid = set(spec.actions) - _VALID_ACTIONS
        assert not invalid, f"{spec.type_id}: unknown actions {invalid}"

    @pytest.mark.parametrize("spec", AZURE_RESOURCE_TYPES)
    def test_has_at_least_one_action(self, spec: ResourceTypeSpec):
        assert len(spec.actions) >= 1, f"{spec.type_id} has no actions"

    def test_azure_vm_has_convert_spot(self):
        spec = get_registry().get("microsoft.compute/virtualmachines")
        assert spec is not None
        assert "convert_spot" in spec.actions


# ---------------------------------------------------------------------------
# Adapter _metrics_for() helpers
# ---------------------------------------------------------------------------
class TestAWSMetricsFor:
    def test_known_type_returns_tuples(self):
        from adapters.aws.cloudwatch import _metrics_for
        result = _metrics_for("AWS::EC2::Instance")
        assert result is not None
        assert len(result) >= 1
        name, namespace, stat, dim = result[0]
        assert name == "CPUUtilization"
        assert namespace == "AWS/EC2"
        assert stat == "Average"
        assert dim == "InstanceId"

    def test_unknown_type_returns_none(self):
        from adapters.aws.cloudwatch import _metrics_for
        assert _metrics_for("AWS::Unknown::Resource") is None

    def test_tuple_length_is_4(self):
        from adapters.aws.cloudwatch import _metrics_for
        result = _metrics_for("AWS::Lambda::Function")
        assert result is not None
        for t in result:
            assert len(t) == 4

    def test_rds_has_connections_metric(self):
        from adapters.aws.cloudwatch import _metrics_for
        result = _metrics_for("AWS::RDS::DBInstance")
        assert result is not None
        names = [t[0] for t in result]
        assert "DatabaseConnections" in names


class TestGCPMetricsFor:
    def test_known_type_returns_tuples(self):
        from adapters.gcp.cloud_monitoring import _metrics_for
        result = _metrics_for("compute.googleapis.com/Instance")
        assert result is not None
        assert len(result) >= 1
        metric_type, stat = result[0]
        assert "cpu" in metric_type
        assert stat in ("mean", "sum")

    def test_unknown_type_returns_none(self):
        from adapters.gcp.cloud_monitoring import _metrics_for
        assert _metrics_for("unknown.googleapis.com/Resource") is None

    def test_tuple_length_is_2(self):
        from adapters.gcp.cloud_monitoring import _metrics_for
        result = _metrics_for("sqladmin.googleapis.com/Instance")
        assert result is not None
        for t in result:
            assert len(t) == 2


class TestAzureMetricsFor:
    def test_known_type_returns_tuples(self):
        from adapters.azure.monitor import _metrics_for
        result = _metrics_for("microsoft.compute/virtualmachines")
        assert result is not None
        assert len(result) >= 1
        metric_name, agg = result[0]
        assert metric_name == "Percentage CPU"
        assert agg in ("Average", "Total", "Minimum", "Maximum")

    def test_case_insensitive_lookup(self):
        from adapters.azure.monitor import _metrics_for
        lower = _metrics_for("microsoft.compute/virtualmachines")
        upper = _metrics_for("Microsoft.Compute/VirtualMachines")
        assert lower == upper

    def test_unknown_type_returns_none(self):
        from adapters.azure.monitor import _metrics_for
        assert _metrics_for("microsoft.unknown/resource") is None

    def test_tuple_length_is_2(self):
        from adapters.azure.monitor import _metrics_for
        result = _metrics_for("microsoft.cache/redis")
        assert result is not None
        for t in result:
            assert len(t) == 2


# ---------------------------------------------------------------------------
# Report generator uses registry display names
# ---------------------------------------------------------------------------
class TestReportGeneratorDisplayNames:
    def _make_finding_dict(self, resource_type: str) -> dict:
        return {
            "resource_id": "arn:aws:ec2:us-east-1:123:instance/i-abc",
            "resource_type": resource_type,
            "name": "test-instance",
            "estimated_monthly_cost": 50.0,
            "priority": "high",
            "waste_reason": "idle",
            "recommendation": "delete",
            "metrics_summary": {},
            "tags": {},
            "last_activity": None,
            "cloud": "aws",
            "region": "us-east-1",
            "account": "123456789012",
        }

    def test_display_name_used_in_slack_block(self):
        from unittest.mock import MagicMock, patch
        from core.reports.generator import build_slack_payload

        finding = self._make_finding_dict("AWS::EC2::Instance")
        report = {
            "scan_id": "test",
            "cloud": "aws",
            "accounts_scanned": ["123"],
            "total_estimated_waste_usd": 50.0,
            "findings_count": 1,
            "findings": [finding],
            "executive_summary": "test summary",
            "generated_at": "2024-01-01T00:00:00Z",
            "skipped_resource_types": [],
        }

        payload = build_slack_payload(report)
        full_text = str(payload)
        # "EC2 Instance" should appear, not the raw "AWS::EC2::Instance"
        assert "EC2 Instance" in full_text

    def test_unknown_type_falls_back_to_type_id(self):
        from core.registry import get_registry
        result = get_registry().display_name("AWS::Unknown::Type")
        assert result == "AWS::Unknown::Type"


# ---------------------------------------------------------------------------
# actions_section() and prompt integration
# ---------------------------------------------------------------------------
class TestActionsSection:
    def test_returns_string_for_aws(self):
        section = actions_section("aws")
        assert isinstance(section, str)
        assert len(section) > 0

    def test_contains_delete_action(self):
        section = actions_section("aws")
        assert "delete" in section

    def test_contains_resize_action(self):
        section = actions_section("aws")
        assert "resize" in section

    def test_groups_by_service(self):
        section = actions_section("aws")
        assert "Compute" in section
        assert "Database" in section

    def test_empty_for_unknown_cloud(self):
        assert actions_section("unknown_cloud") == ""

    def test_gcp_section_contains_gce(self):
        section = actions_section("gcp")
        assert "GCE Instance" in section

    def test_azure_section_contains_vm(self):
        section = actions_section("azure")
        assert "Virtual Machine" in section

    def test_prompt_includes_actions_section(self):
        from core.agent.prompts import build_system_prompt
        prompt = build_system_prompt("aws", [], [{"name": "prod", "id": "123"}])
        assert "REMEDIATION ACTIONS" in prompt
        assert "EC2 Instance" in prompt
        assert "delete" in prompt

    def test_chat_prompt_includes_actions_section(self):
        from core.agent.prompts import build_chat_system_prompt
        prompt = build_chat_system_prompt("gcp", [], [{"name": "proj", "id": "my-project"}])
        assert "REMEDIATION ACTIONS" in prompt
        assert "GCE Instance" in prompt
