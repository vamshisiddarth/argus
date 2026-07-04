from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from core.remediation.loader import PolicyLoadError, load_policies


def _write(tmp_path: Path, filename: str, content: str) -> Path:
    f = tmp_path / filename
    f.write_text(textwrap.dedent(content))
    return f


def _minimal(
    policy_id: str = "rds-resize",
    resource_type: str = "AWS::RDS::DBInstance",
    action: str = "resize",
    weight: int = 10,
    extra: str = "",
) -> str:
    base = f"""\
version: "1"
policy_id: {policy_id}
name: Resize underutilized RDS
resource_type: "{resource_type}"
action: {action}
weight: {weight}
"""
    if extra:
        base += textwrap.dedent(extra).strip() + "\n"
    return base


class TestLoadPoliciesDirectory:
    def test_missing_dir_returns_empty(self, tmp_path):
        result = load_policies(tmp_path / "nonexistent")
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path):
        result = load_policies(tmp_path)
        assert result == []

    def test_loads_single_valid_file(self, tmp_path):
        _write(tmp_path, "rds.yaml", _minimal())
        policies = load_policies(tmp_path)
        assert len(policies) == 1
        assert policies[0].policy_id == "rds-resize"

    def test_loads_multiple_files(self, tmp_path):
        _write(tmp_path, "rds.yaml", _minimal("rds-resize"))
        _write(tmp_path, "ec2.yaml", _minimal("ec2-stop", action="stop"))
        policies = load_policies(tmp_path)
        assert len(policies) == 2
        ids = {p.policy_id for p in policies}
        assert ids == {"rds-resize", "ec2-stop"}

    def test_glob_recurses_subdirs(self, tmp_path):
        sub = tmp_path / "aws"
        sub.mkdir()
        _write(sub, "rds.yaml", _minimal("rds-resize"))
        policies = load_policies(tmp_path)
        assert len(policies) == 1

    def test_error_in_one_file_raises(self, tmp_path):
        _write(tmp_path, "good.yaml", _minimal("rds-resize"))
        _write(tmp_path, "bad.yaml", "version: '1'\npolicy_id: x\n")
        with pytest.raises(PolicyLoadError):
            load_policies(tmp_path)


class TestSchemaValidation:
    def test_missing_version_raises(self, tmp_path):
        _write(tmp_path, "p.yaml", "policy_id: x\nname: X\n")
        with pytest.raises(PolicyLoadError, match="unsupported version"):
            load_policies(tmp_path)

    def test_unsupported_version_raises(self, tmp_path):
        _write(tmp_path, "p.yaml", _minimal().replace('version: "1"', 'version: "99"'))
        with pytest.raises(PolicyLoadError, match="unsupported version"):
            load_policies(tmp_path)

    def test_missing_policy_id_raises(self, tmp_path):
        content = _minimal().replace("policy_id: rds-resize\n", "")
        _write(tmp_path, "p.yaml", content)
        with pytest.raises(PolicyLoadError, match="policy_id"):
            load_policies(tmp_path)

    def test_missing_action_raises(self, tmp_path):
        content = _minimal().replace("action: resize\n", "")
        _write(tmp_path, "p.yaml", content)
        with pytest.raises(PolicyLoadError, match="action"):
            load_policies(tmp_path)

    def test_invalid_action_raises(self, tmp_path):
        _write(tmp_path, "p.yaml", _minimal(action="fly"))
        with pytest.raises(PolicyLoadError, match="invalid action"):
            load_policies(tmp_path)

    def test_invalid_weight_raises(self, tmp_path):
        _write(tmp_path, "p.yaml", _minimal(extra="weight: abc"))
        with pytest.raises(PolicyLoadError, match="weight"):
            load_policies(tmp_path)

    def test_invalid_yaml_raises(self, tmp_path):
        _write(tmp_path, "p.yaml", "key: [unclosed")
        with pytest.raises(PolicyLoadError, match="invalid YAML"):
            load_policies(tmp_path)

    def test_invalid_yaml_includes_line_number(self, tmp_path):
        # Multi-line file: error is on line 3 (0-indexed line 2 → displayed as 3)
        _write(tmp_path, "p.yaml", "version: '1'\nkey: value\n  bad: indent: here: :")
        try:
            load_policies(tmp_path)
        except PolicyLoadError as exc:
            msg = str(exc)
            # Should include filename:line: pattern (e.g. "p.yaml:3:1:")
            assert "p.yaml" in msg
            # Line number should appear as a digit after the colon
            import re
            assert re.search(r"p\.yaml:\d+:\d+", msg), (
                f"Expected line:col in error, got: {msg}"
            )

    def test_unknown_resource_type_warns_but_loads(self, tmp_path, caplog):
        import logging

        _write(tmp_path, "p.yaml", _minimal(resource_type="AWS::Fake::Resource"))
        with caplog.at_level(logging.WARNING):
            policies = load_policies(tmp_path)
        assert len(policies) == 1
        assert any("unknown_resource_type" in r.message for r in caplog.records)

    def test_wildcard_resource_type_loads(self, tmp_path):
        _write(tmp_path, "p.yaml", _minimal(resource_type="*"))
        policies = load_policies(tmp_path)
        assert policies[0].resource_type == "*"


class TestConditionParsing:
    def test_tier1_conditions_parsed(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        conditions:
          min_estimated_monthly_cost_usd: 100
          ai_priority: [high, medium]
          idle_days_min: 7
        """
            ),
        )
        p = load_policies(tmp_path)[0]
        assert p.conditions.min_estimated_monthly_cost_usd == 100.0
        assert p.conditions.ai_priority == ("high", "medium")
        assert p.conditions.idle_days_min == 7

    def test_tier2_metric_conditions_parsed(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        conditions:
          metrics:
            - metric: CPUUtilization_avg
              operator: lt
              threshold: 30
        """
            ),
        )
        p = load_policies(tmp_path)[0]
        assert len(p.conditions.metrics) == 1
        assert p.conditions.metrics[0].metric == "CPUUtilization_avg"
        assert p.conditions.metrics[0].operator == "lt"
        assert p.conditions.metrics[0].threshold == 30.0

    def test_invalid_metric_operator_raises(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        conditions:
          metrics:
            - metric: CPU
              operator: between
              threshold: 30
        """
            ),
        )
        with pytest.raises(PolicyLoadError):
            load_policies(tmp_path)

    def test_metric_missing_threshold_raises(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        conditions:
          metrics:
            - metric: CPU
              operator: lt
        """
            ),
        )
        with pytest.raises(PolicyLoadError, match="threshold"):
            load_policies(tmp_path)

    def test_invalid_ai_priority_raises(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        conditions:
          ai_priority: [critical]
        """
            ),
        )
        with pytest.raises(PolicyLoadError):
            load_policies(tmp_path)


class TestScopeFilterParsing:
    def test_include_fields_parsed(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        include:
          cloud_platforms: [aws]
          accounts: ["123456"]
          regions: [eu-west-1]
          tags:
            - environment: [prod, staging]
        """
            ),
        )
        p = load_policies(tmp_path)[0]
        assert p.include.cloud_platforms == ("aws",)
        assert p.include.accounts == ("123456",)
        assert p.include.regions == ("eu-west-1",)
        assert p.include.tags == ({"environment": ["prod", "staging"]},)

    def test_exclude_fields_parsed(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        exclude:
          tags:
            - do-not-touch: ["true"]
        """
            ),
        )
        p = load_policies(tmp_path)[0]
        assert p.exclude.tags == ({"do-not-touch": ["true"]},)

    def test_omitted_scope_defaults_to_none(self, tmp_path):
        _write(tmp_path, "p.yaml", _minimal())
        p = load_policies(tmp_path)[0]
        assert p.include.cloud_platforms is None
        assert p.include.accounts is None
        assert p.include.regions is None
        assert p.include.tags == ()

    def test_tags_not_single_key_raises(self, tmp_path):
        _write(
            tmp_path,
            "p.yaml",
            _minimal(
                extra="""
        include:
          tags:
            - environment: [prod]
              team: [platform]
        """
            ),
        )
        with pytest.raises(PolicyLoadError, match="single-key"):
            load_policies(tmp_path)


