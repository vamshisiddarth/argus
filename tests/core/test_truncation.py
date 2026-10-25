"""Model output cut off by the output-token limit (stop_reason max_tokens)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import AgentLoop
from core.agent.prompts import build_tool_schemas
from core.errors import AgentDidNotSubmitError

ACCOUNTS = [{"id": "123456789012", "name": "t"}]
NAT = "AWS::EC2::NatGateway"


class Adapter(CloudAdapter):
    def list_resources(self, ignore_regions=None):
        return [Resource(f"nat-{i}", NAT, "aws", "us-east-1") for i in range(4)]

    def get_metrics(self, resource_id, resource_type, days=90):
        return MetricSummary(resource_id, resource_type, days, {"b": 0.0})

    def get_cost(self, resource_ids, days=30):
        return {}

    def get_last_activity(self, resource_id, resource_type):
        return datetime(2026, 4, 1, tzinfo=timezone.utc)


def _finding(rid):
    return {
        "resource_id": rid,
        "resource_type": NAT,
        "cloud": "aws",
        "region": "us-east-1",
        "estimated_monthly_cost": 30.0,
        "waste_reason": "idle",
        "recommendation": "delete",
        "priority": "high",
        "metrics_summary": {},
        "tags": {},
    }


def _submit(findings, summary="s", partial=None, tid="t"):
    args = {"findings": findings, "executive_summary": summary}
    if partial is not None:
        args["partial"] = partial
    return AIResponse("tool_use", None, [ToolCall(tid, "submit_findings", args)])


def _cut_off(text="Found these idle NATs:"):
    return AIResponse("max_tokens", text, [])


def _run(responses):
    fake_ai = MagicMock(spec=AIProvider)
    fake_ai.chat.side_effect = responses
    out = AgentLoop(fake_ai, Adapter()).run("aws", [], ACCOUNTS)
    return out, fake_ai


def test_schema_documents_partial_submissions():
    submit = next(t for t in build_tool_schemas() if t["name"] == "submit_findings")
    assert submit["input_schema"]["properties"]["partial"]["type"] == "boolean"


def test_truncation_triggers_a_batching_instruction_not_the_generic_reminder():
    _, fake_ai = _run(
        [_cut_off(), _submit([_finding("nat-0")], partial=False)],
    )

    follow_up = fake_ai.chat.call_args_list[1].args[0][-1]
    assert follow_up.role == "user"
    assert "output limit" in follow_up.text
    assert "partial" in follow_up.text


def test_batches_are_merged_and_summary_comes_from_the_last_call():
    (findings, summary), fake_ai = _run(
        [
            _cut_off(),
            _submit([_finding("nat-0"), _finding("nat-1")], "first", partial=True),
            _submit([_finding("nat-2")], "the real summary", partial=False, tid="t2"),
        ]
    )

    assert sorted(f.resource_id for f in findings) == ["nat-0", "nat-1", "nat-2"]
    assert summary == "the real summary"


def test_partial_batch_gets_a_tool_result_so_the_conversation_stays_valid():
    _, fake_ai = _run(
        [
            _submit([_finding("nat-0")], partial=True),
            _submit([_finding("nat-1")], partial=False, tid="t2"),
        ]
    )

    last = fake_ai.chat.call_args_list[1].args[0][-1]
    assert last.tool_results and last.tool_results[0].tool_call_id == "t"
    assert "1 finding" in last.tool_results[0].content


def test_duplicate_resources_across_batches_are_kept_once():
    (findings, _), _ = _run(
        [
            _submit([_finding("nat-0")], partial=True),
            _submit([_finding("nat-0"), _finding("nat-1")], partial=False, tid="t2"),
        ]
    )

    assert sorted(f.resource_id for f in findings) == ["nat-0", "nat-1"]


def test_repeated_truncation_fails_and_names_the_setting():
    with pytest.raises(AgentDidNotSubmitError, match="AI_MAX_TOKENS"):
        _run([_cut_off()] * 6)


def test_truncation_does_not_use_up_the_end_turn_reminder():
    (findings, _), _ = _run(
        [
            _cut_off(),
            AIResponse("end_turn", "I think there are some", []),
            _submit([_finding("nat-0")], partial=False),
        ]
    )

    assert [f.resource_id for f in findings] == ["nat-0"]


def test_unflagged_single_submit_still_works():
    (findings, summary), _ = _run([_submit([_finding("nat-0")], "ok")])

    assert len(findings) == 1 and summary == "ok"


class TestFindingTagsComeFromTheInventory:
    class TaggedAdapter(Adapter):
        def list_resources(self, ignore_regions=None):
            return [
                Resource(
                    "nat-0", NAT, "aws", "us-east-1", tags={"environment": "prod"}
                ),
                Resource("nat-1", NAT, "aws", "us-east-1"),
            ]

    def _run(self, findings):
        fake_ai = MagicMock(spec=AIProvider)
        fake_ai.chat.side_effect = [_submit(findings)]
        out, _ = AgentLoop(fake_ai, self.TaggedAdapter()).run("aws", [], ACCOUNTS)
        return {f.resource_id: f for f in out}

    def test_model_dropping_tags_does_not_lose_them(self):
        by_id = self._run([_finding("nat-0")])  # model returned tags={}

        assert by_id["nat-0"].tags == {"environment": "prod"}

    def test_model_inventing_tags_is_overridden_by_the_real_ones(self):
        f = _finding("nat-0")
        f["tags"] = {"environment": "dev"}

        assert self._run([f])["nat-0"].tags == {"environment": "prod"}

    def test_untagged_resource_stays_untagged(self):
        f = _finding("nat-1")
        f["tags"] = {"made": "up"}

        assert self._run([f])["nat-1"].tags == {}

    def test_unknown_resource_keeps_the_models_tags(self):
        f = _finding("nat-unknown")
        f["tags"] = {"team": "x"}

        assert self._run([f])["nat-unknown"].tags == {"team": "x"}
