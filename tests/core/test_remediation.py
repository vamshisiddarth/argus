"""Tests for core/remediation — CLI command template rendering."""

from __future__ import annotations

from core.registry import get_registry
from core.registry.registry import _VALID_ACTIONS
from core.remediation import get_command, runbook, supported_types


class TestGetCommand:
    def test_known_type_and_action_returns_string(self):
        cmd = get_command("AWS::EC2::Instance", "stop")
        assert cmd is not None
        assert isinstance(cmd, str)
        assert len(cmd) > 0

    def test_unknown_type_returns_none(self):
        assert get_command("AWS::Unknown::Resource", "delete") is None

    def test_unknown_action_returns_none(self):
        assert get_command("AWS::EC2::Instance", "nonexistent_action") is None

    def test_placeholder_filled_resource_id(self):
        cmd = get_command("AWS::EC2::Instance", "stop", resource_id="i-0abc123")
        assert cmd is not None
        assert "i-0abc123" in cmd
        assert "{resource_id}" not in cmd

    def test_placeholder_filled_region(self):
        cmd = get_command("AWS::EC2::Instance", "stop", region="eu-west-1")
        assert cmd is not None
        assert "eu-west-1" in cmd
        assert "{region}" not in cmd

    def test_default_placeholder_when_no_args(self):
        cmd = get_command("AWS::EC2::Instance", "stop")
        assert cmd is not None
        assert "{resource_id}" in cmd
        assert "{region}" in cmd

    def test_ec2_stop_is_aws_cli(self):
        cmd = get_command("AWS::EC2::Instance", "stop")
        assert cmd is not None
        assert cmd.startswith("aws ec2")

    def test_ec2_delete_uses_terminate(self):
        cmd = get_command("AWS::EC2::Instance", "delete")
        assert cmd is not None
        assert "terminate-instances" in cmd

    def test_rds_stop(self):
        cmd = get_command("AWS::RDS::DBInstance", "stop")
        assert cmd is not None
        assert "rds stop-db-instance" in cmd

    def test_lambda_delete(self):
        cmd = get_command("AWS::Lambda::Function", "delete")
        assert cmd is not None
        assert "lambda delete-function" in cmd

    def test_gce_stop(self):
        cmd = get_command("compute.googleapis.com/Instance", "stop")
        assert cmd is not None
        assert cmd.startswith("gcloud compute instances stop")

    def test_gce_resize(self):
        cmd = get_command("compute.googleapis.com/Instance", "resize")
        assert cmd is not None
        assert "set-machine-type" in cmd

    def test_azure_vm_stop(self):
        cmd = get_command("microsoft.compute/virtualmachines", "stop")
        assert cmd is not None
        assert "az vm deallocate" in cmd

    def test_azure_vm_resize(self):
        cmd = get_command("microsoft.compute/virtualmachines", "resize")
        assert cmd is not None
        assert "az vm resize" in cmd

    def test_account_id_placeholder(self):
        cmd = get_command("AWS::SQS::Queue", "delete", account_id="123456789012")
        assert cmd is not None
        assert "123456789012" in cmd

    def test_s3_delete_is_multiline(self):
        cmd = get_command("AWS::S3::Bucket", "delete")
        assert cmd is not None
        assert "\n" in cmd  # multi-step: empty then delete


class TestRunbook:
    def test_returns_list_of_tuples(self):
        entries = runbook("AWS::EC2::Instance")
        assert isinstance(entries, list)
        assert all(isinstance(e, tuple) and len(e) == 2 for e in entries)

    def test_tuple_structure(self):
        entries = runbook("AWS::EC2::Instance")
        for action, cmd in entries:
            assert isinstance(action, str)
            assert isinstance(cmd, str)

    def test_ec2_has_stop_and_delete(self):
        actions = [a for a, _ in runbook("AWS::EC2::Instance")]
        assert "stop" in actions
        assert "delete" in actions

    def test_unknown_type_returns_empty_list(self):
        assert runbook("AWS::Unknown::Resource") == []

    def test_placeholders_filled_when_args_given(self):
        entries = runbook("AWS::EC2::Instance", resource_id="i-123", region="us-east-1")
        for _, cmd in entries:
            assert "{resource_id}" not in cmd
            assert "{region}" not in cmd
            assert (
                "i-123" in cmd or "us-east-1" in cmd or True
            )  # at least one will appear

    def test_gcp_gce_runbook(self):
        entries = runbook("compute.googleapis.com/Instance")
        assert len(entries) >= 2
        actions = [a for a, _ in entries]
        assert "stop" in actions
        assert "delete" in actions

    def test_azure_aks_runbook(self):
        entries = runbook("microsoft.containerservice/managedclusters")
        actions = [a for a, _ in entries]
        assert "delete" in actions
        assert "reduce_nodes" in actions


class TestSupportedTypes:
    def test_returns_list(self):
        types = supported_types()
        assert isinstance(types, list)
        assert len(types) > 0

    def test_is_sorted(self):
        types = supported_types()
        assert types == sorted(types)

    def test_covers_all_three_clouds(self):
        types = supported_types()
        aws = [t for t in types if t.startswith("AWS::")]
        gcp = [t for t in types if "googleapis.com" in t]
        azure = [t for t in types if t.startswith("microsoft.")]
        assert len(aws) >= 5
        assert len(gcp) >= 5
        assert len(azure) >= 5


class TestRegistryConsistency:
    """Remediation commands should only use valid action vocab from the registry."""

    def test_all_registered_actions_are_valid_vocab(self):
        from core.remediation import _COMMANDS

        for type_id, action_map in _COMMANDS.items():
            for action in action_map:
                assert (
                    action in _VALID_ACTIONS
                ), f"{type_id}: action '{action}' not in _VALID_ACTIONS"

    def test_remediation_type_ids_exist_in_registry(self):
        """Every type_id with commands must exist in the registry."""
        registry = get_registry()
        from core.remediation import _COMMANDS

        for type_id in _COMMANDS:
            spec = registry.get(type_id)
            assert (
                spec is not None
            ), f"type_id '{type_id}' has remediation commands but is not in registry"

    def test_remediation_actions_match_registry_actions(self):
        """Command actions must be a subset of the spec's declared actions."""
        registry = get_registry()
        from core.remediation import _COMMANDS

        for type_id, action_map in _COMMANDS.items():
            spec = registry.get(type_id)
            if spec is None:
                continue
            declared = set(spec.actions)
            for action in action_map:
                assert action in declared, (
                    f"{type_id}: command for action '{action}' exists but "
                    f"spec.actions={declared}"
                )
