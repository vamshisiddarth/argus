"""
End-to-end remediation flow test.

Exercises the full pipeline without any real cloud calls or real Jira:

  YAML policy file(s)
      │
      ▼  load_policies()
  Policy objects
      │
      ▼  validate_policies()
  ValidationResult (must be clean)
      │
      ▼  engine.evaluate()
  ChangeProposal objects (with UUID, runbook, cost)
      │
      ▼  JiraTracker.create()  [mocked Jira client]
  Jira ticket URL returned + audit log written

Each layer is real code; only the HTTP boundary (JiraClient) is mocked.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.models.finding import ResourceFinding
from core.remediation.audit import log_proposal
from core.remediation.engine import evaluate
from core.remediation.loader import load_policies
from core.remediation.models import ChangeProposal
from core.remediation.validator import validate_policies
from integrations.jira.tracker import JiraTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_policy(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content))


def _finding(
    resource_id: str = "i-abc123",
    resource_type: str = "AWS::EC2::Instance",
    cloud: str = "aws",
    region: str = "us-east-1",
    cost: float = 200.0,
    priority: str = "high",
    idle_days: int = 20,
    metrics: dict | None = None,
    tags: dict | None = None,
) -> ResourceFinding:
    from datetime import timedelta

    last_activity = datetime.now(tz=timezone.utc) - timedelta(days=idle_days)
    return ResourceFinding(
        resource_id=resource_id,
        resource_type=resource_type,
        cloud=cloud,
        region=region,
        name=resource_id,
        estimated_monthly_cost=cost,
        waste_reason=f"CPU < 2% for {idle_days} days, no meaningful traffic",
        recommendation="Stop or terminate the instance",
        priority=priority,
        metrics_summary=metrics or {"CPUUtilization": 1.2, "NetworkOut": 512.0},
        tags=tags or {},
        last_activity=last_activity,
        scan_time=datetime.now(tz=timezone.utc),
    )


def _mock_jira_client(new_key: str = "INFRA-42") -> MagicMock:
    client = MagicMock()
    client.search.return_value = []  # no existing ticket
    client.create_issue.return_value = {"key": new_key, "self": f"https://jira.example.com/rest/api/3/issue/{new_key}"}
    client.issue_url.side_effect = lambda key: f"https://jira.example.com/browse/{key}"
    return client


# ---------------------------------------------------------------------------
# Full pipeline E2E
# ---------------------------------------------------------------------------


class TestRemediationE2E:
    def test_full_pipeline_creates_jira_ticket(self, tmp_path):
        """
        Load a policy → validate → evaluate finding → create Jira ticket.
        Verifies every layer produces the expected output.
        """
        # 1. Write a real policy YAML file
        _write_policy(
            tmp_path / "ec2-stop.yaml",
            """\
            version: "1"
            policy_id: ec2-stop-idle
            name: Stop idle EC2 instances
            resource_type: AWS::EC2::Instance
            action: stop
            weight: 10
            conditions:
              ai_priority: [high, medium]
              min_estimated_monthly_cost_usd: 50
              idle_days_min: 14
              metrics:
                - metric: CPUUtilization
                  operator: lt
                  threshold: 5.0
            exclude:
              tags:
                - environment: [prod, production]
            """,
        )

        # 2. Load and validate
        policies = load_policies(tmp_path)
        assert len(policies) == 1
        result = validate_policies(policies)
        assert result.ok, f"Validation errors: {result.errors}"

        # 3. Evaluate against a matching finding
        finding = _finding(cost=200.0, priority="high", idle_days=20)
        proposals = evaluate([finding], policies)
        assert len(proposals) == 1

        proposal = proposals[0]
        assert proposal.policy.policy_id == "ec2-stop-idle"
        assert proposal.policy.action == "stop"
        assert proposal.estimated_monthly_cost_usd == 200.0
        assert proposal.proposal_id  # UUID present
        assert "stop-instances" in proposal.runbook or proposal.runbook  # runbook built

        # 4. Create Jira ticket (mocked HTTP)
        client = _mock_jira_client("INFRA-42")
        tracker = JiraTracker(
            client,
            project="INFRA",
            issue_type="Task",
            default_labels=["argus", "cost-optimization"],
            priority_map={"high": "High", "medium": "Medium", "low": "Low"},
        )
        url = tracker.create(proposal)

        assert "INFRA-42" in url
        client.create_issue.assert_called_once()

        # Verify issue fields structure
        fields = client.create_issue.call_args[0][0]
        assert fields["project"]["key"] == "INFRA"
        assert "i-abc123" in fields["summary"]
        assert "200" in fields["summary"]
        assert "high" in fields["summary"]

        # ADF description must have content sections
        desc = fields["description"]
        assert desc["type"] == "doc"
        adf_text = _flatten_adf(desc)
        assert "CPU < 2%" in adf_text           # waste_reason in description
        assert "Human approval required" in adf_text
        assert proposal.proposal_id in adf_text  # proposal UUID traceable

        # Labels include dedup label and priority/action labels
        labels = fields["labels"]
        assert any("argus:" in lbl for lbl in labels)          # dedup label
        assert "argus-priority-high" in labels
        assert "argus-action-stop" in labels

    def test_finding_excluded_by_tag_produces_no_proposal(self, tmp_path):
        """A production-tagged resource must never match a policy with prod exclusion."""
        _write_policy(
            tmp_path / "ec2-stop.yaml",
            """\
            version: "1"
            policy_id: ec2-stop-idle
            name: Stop idle EC2 instances
            resource_type: AWS::EC2::Instance
            action: stop
            weight: 10
            conditions:
              ai_priority: [high]
            exclude:
              tags:
                - environment: [prod, production]
            """,
        )
        policies = load_policies(tmp_path)
        finding = _finding(tags={"environment": "production"})
        proposals = evaluate([finding], policies)
        assert proposals == []

    def test_two_policies_weight_ordering(self, tmp_path):
        """Higher-weight policy wins; lower-weight acts as catch-all."""
        _write_policy(
            tmp_path / "high.yaml",
            """\
            version: "1"
            policy_id: high-cost-resize
            name: Resize high-cost idle EC2
            resource_type: AWS::EC2::Instance
            action: resize
            weight: 20
            conditions:
              min_estimated_monthly_cost_usd: 100
            """,
        )
        _write_policy(
            tmp_path / "low.yaml",
            """\
            version: "1"
            policy_id: catch-all-stop
            name: Stop any idle EC2
            resource_type: AWS::EC2::Instance
            action: stop
            weight: 5
            """,
        )
        policies = load_policies(tmp_path)
        assert validate_policies(policies).ok

        expensive = _finding("i-expensive", cost=500.0)
        cheap = _finding("i-cheap", cost=20.0)

        proposals = evaluate([expensive, cheap], policies)
        assert len(proposals) == 2

        by_resource = {p.finding.resource_id: p for p in proposals}
        assert by_resource["i-expensive"].policy.action == "resize"   # high-weight matched
        assert by_resource["i-cheap"].policy.action == "stop"         # fell through to catch-all

    def test_duplicate_resource_id_deduped(self, tmp_path):
        """Same resource appearing twice in findings produces one proposal."""
        _write_policy(
            tmp_path / "p.yaml",
            """\
            version: "1"
            policy_id: ec2-stop
            name: Stop idle
            resource_type: AWS::EC2::Instance
            action: stop
            weight: 10
            """,
        )
        policies = load_policies(tmp_path)
        f1 = _finding("i-dup", cost=100.0)
        f2 = _finding("i-dup", cost=100.0)
        proposals = evaluate([f1, f2], policies)
        assert len(proposals) == 1

    def test_audit_log_written(self, tmp_path):
        """log_proposal appends a parseable JSONL line."""
        from core.remediation.models import Condition, Policy, ScopeFilter

        policy = Policy(
            policy_id="test-p",
            name="Test",
            resource_type="AWS::EC2::Instance",
            conditions=Condition(),
            action="stop",
            weight=5,
        )
        finding = _finding()
        proposal = ChangeProposal(
            finding=finding,
            policy=policy,
            runbook="aws ec2 stop-instances --instance-ids i-abc123",
            estimated_monthly_cost_usd=200.0,
        )

        audit_file = tmp_path / "audit.jsonl"
        log_proposal(proposal, jira_key="INFRA-1", jira_url="https://jira.example.com/browse/INFRA-1", audit_path=str(audit_file))

        assert audit_file.exists()
        line = json.loads(audit_file.read_text().strip())
        assert line["proposal_id"] == proposal.proposal_id
        assert line["resource_id"] == "i-abc123"
        assert line["policy_id"] == "test-p"
        assert line["jira_key"] == "INFRA-1"
        assert line["jira_url"] == "https://jira.example.com/browse/INFRA-1"
        assert line["estimated_monthly_cost_usd"] == 200.0

    def test_jira_dedup_updates_existing_ticket(self, tmp_path):
        """Second run for same resource updates existing ticket, not create new."""
        _write_policy(
            tmp_path / "p.yaml",
            """\
            version: "1"
            policy_id: ec2-stop
            name: Stop idle
            resource_type: AWS::EC2::Instance
            action: stop
            weight: 10
            """,
        )
        policies = load_policies(tmp_path)
        finding = _finding()
        proposals = evaluate([finding], policies)
        assert len(proposals) == 1

        # Simulate existing open ticket with stale fingerprint
        client = MagicMock()
        client.search.return_value = [
            {
                "key": "INFRA-7",
                "fields": {
                    "description": "old description without snapshot",
                    "status": {"name": "In Progress"},
                },
            }
        ]
        client.issue_url.side_effect = lambda key: f"https://jira.example.com/browse/{key}"

        tracker = JiraTracker(client, project="INFRA", issue_type="Task",
                              default_labels=["argus"], priority_map={})
        url = tracker.create(proposals[0])

        assert "INFRA-7" in url
        client.create_issue.assert_not_called()   # no new ticket
        client.add_comment.assert_called_once()   # comment added instead

    def test_invalid_policy_action_for_type_rejected(self, tmp_path):
        """convert_spot is not valid for RDS — loader must reject at load time."""
        from core.remediation.loader import PolicyLoadError

        _write_policy(
            tmp_path / "bad.yaml",
            """\
            version: "1"
            policy_id: bad-policy
            name: Bad
            resource_type: AWS::RDS::DBInstance
            action: convert_spot
            weight: 10
            """,
        )
        with pytest.raises(PolicyLoadError, match="not valid for resource type"):
            load_policies(tmp_path)

    def test_sample_policies_all_load_and_validate(self):
        """The bundled config/policies/ files must all load and pass validation."""
        sample_dir = Path(__file__).parent.parent.parent / "config" / "policies"
        if not sample_dir.exists():
            pytest.skip("config/policies/ not present")

        policies = load_policies(sample_dir)
        assert len(policies) >= 5, f"Expected ≥5 sample policies, got {len(policies)}"

        result = validate_policies(policies)
        assert result.ok, f"Sample policies have errors: {result.errors}"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _flatten_adf(node: object) -> str:
    parts: list[str] = []

    def _walk(n: object) -> None:
        if isinstance(n, dict):
            if n.get("type") == "text":
                parts.append(n.get("text", ""))
            for child in n.get("content", []):
                _walk(child)
        elif isinstance(n, list):
            for item in n:
                _walk(item)

    _walk(node)
    return " ".join(parts)
