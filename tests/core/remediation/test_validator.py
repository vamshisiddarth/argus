from __future__ import annotations

from core.remediation.models import Condition, Policy, ScopeFilter
from core.remediation.validator import validate_policies


def _policy(
    policy_id: str,
    resource_type: str = "AWS::RDS::DBInstance",
    action: str = "resize",
    weight: int = 10,
    include: ScopeFilter | None = None,
    exclude: ScopeFilter | None = None,
    source_file: str = "test.yaml",
) -> Policy:
    return Policy(
        policy_id=policy_id,
        name=f"Policy {policy_id}",
        resource_type=resource_type,
        conditions=Condition(),
        action=action,
        weight=weight,
        include=include or ScopeFilter(),
        exclude=exclude or ScopeFilter(),
        source_file=source_file,
    )


class TestDuplicateIds:
    def test_unique_ids_no_error(self):
        # Different resource types — no conflict possible even with same weight
        result = validate_policies(
            [
                _policy("a", resource_type="AWS::RDS::DBInstance"),
                _policy("b", resource_type="AWS::EC2::Instance", action="stop"),
            ]
        )
        assert result.ok

    def test_duplicate_id_is_error(self):
        result = validate_policies(
            [
                _policy("same-id", source_file="file1.yaml"),
                _policy("same-id", action="stop", source_file="file2.yaml"),
            ]
        )
        assert not result.ok
        assert any("same-id" in e for e in result.errors)
        assert any("file1.yaml" in e for e in result.errors)
        assert any("file2.yaml" in e for e in result.errors)


class TestWeightConflicts:
    def test_same_weight_same_type_no_scope_is_error(self):
        # Both match everything — always conflict
        result = validate_policies(
            [
                _policy("p1", weight=10, action="resize"),
                _policy("p2", weight=10, action="stop"),
            ]
        )
        assert not result.ok
        assert any("p1" in e and "p2" in e for e in result.errors)

    def test_same_weight_same_action_same_scope_is_error(self):
        # Duplicate policies — same action, same scope, same weight
        result = validate_policies(
            [
                _policy("p1", weight=10, action="resize"),
                _policy("p2", weight=10, action="resize"),
            ]
        )
        assert not result.ok

    def test_same_weight_different_type_no_error(self):
        result = validate_policies(
            [
                _policy("p1", resource_type="AWS::RDS::DBInstance", weight=10),
                _policy(
                    "p2", resource_type="AWS::EC2::Instance", weight=10, action="stop"
                ),
            ]
        )
        assert result.ok

    def test_different_weights_no_error(self):
        result = validate_policies(
            [
                _policy("p1", weight=20, action="resize"),
                _policy("p2", weight=10, action="stop"),
            ]
        )
        assert result.ok

    def test_same_weight_disjoint_regions_no_error(self):
        result = validate_policies(
            [
                _policy("p1", weight=10, include=ScopeFilter(regions=("eu-west-1",))),
                _policy(
                    "p2",
                    weight=10,
                    action="stop",
                    include=ScopeFilter(regions=("us-east-1",)),
                ),
            ]
        )
        assert result.ok

    def test_same_weight_disjoint_accounts_no_error(self):
        result = validate_policies(
            [
                _policy("p1", weight=10, include=ScopeFilter(accounts=("111",))),
                _policy(
                    "p2",
                    weight=10,
                    action="stop",
                    include=ScopeFilter(accounts=("222",)),
                ),
            ]
        )
        assert result.ok

    def test_same_weight_overlapping_regions_is_error(self):
        result = validate_policies(
            [
                _policy(
                    "p1",
                    weight=10,
                    include=ScopeFilter(regions=("eu-west-1", "us-east-1")),
                ),
                _policy(
                    "p2",
                    weight=10,
                    action="stop",
                    include=ScopeFilter(regions=("eu-west-1",)),
                ),
            ]
        )
        assert not result.ok

    def test_conflict_error_message_names_both_policies(self):
        result = validate_policies(
            [
                _policy("alpha", weight=10, action="resize"),
                _policy("beta", weight=10, action="stop"),
            ]
        )
        assert not result.ok
        error = result.errors[0]
        assert "alpha" in error
        assert "beta" in error
        assert "weight" in error
        assert "scope overlap" in error.lower() or "overlap" in error.lower()

    def test_conflict_error_message_includes_fix_hint(self):
        result = validate_policies(
            [
                _policy("p1", weight=10, action="resize"),
                _policy("p2", weight=10, action="stop"),
            ]
        )
        error = result.errors[0]
        assert "Fix:" in error


class TestUnreachableWarnings:
    def test_shadowed_policy_is_warning(self):
        # p1 (weight=20, no scope restriction) shadows p2 (weight=10)
        result = validate_policies(
            [
                _policy("p1", weight=20, action="resize"),
                _policy("p2", weight=10, action="stop"),
            ]
        )
        assert result.ok  # warning only, not error
        assert any("p2" in w for w in result.warnings)
        assert any(
            "unreachable" in w.lower() or "shadow" in w.lower() for w in result.warnings
        )

    def test_non_shadowed_lower_weight_no_warning(self):
        # p1 restricts to eu-west-1, p2 handles us-east-1 — not shadowed
        result = validate_policies(
            [
                _policy("p1", weight=20, include=ScopeFilter(regions=("eu-west-1",))),
                _policy(
                    "p2",
                    weight=10,
                    action="stop",
                    include=ScopeFilter(regions=("us-east-1",)),
                ),
            ]
        )
        assert result.ok
        assert result.warnings == []


class TestEmptyPolicies:
    def test_empty_list_is_valid(self):
        result = validate_policies([])
        assert result.ok
        assert result.errors == []
        assert result.warnings == []

    def test_single_policy_always_valid(self):
        result = validate_policies([_policy("only-one")])
        assert result.ok
