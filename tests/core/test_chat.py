from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.chat import MAX_TOOL_ROUNDS, ChatResponse, ChatSession
from core.agent.prompts import (
    build_chat_system_prompt,
    build_chat_tool_schemas,
    build_system_prompt,
)

# ------------------------------------------------------------------
# Fakes (same pattern as test_loop.py)
# ------------------------------------------------------------------


class FakeCloudAdapter(CloudAdapter):
    def list_resources(self, ignore_regions=None):
        return [
            Resource(
                resource_id="nat-0abc123",
                resource_type="AWS::EC2::NatGateway",
                cloud="aws",
                region="us-east-1",
                tags={},
            ),
            Resource(
                resource_id="vol-0def456",
                resource_type="AWS::EC2::Volume",
                cloud="aws",
                region="us-east-1",
                tags={"env": "dev"},
            ),
        ]

    def get_metrics(self, resource_id, resource_type, days=90):
        return MetricSummary(
            resource_id=resource_id,
            resource_type=resource_type,
            period_days=days,
            metrics={"bytes_out_total": 847},
        )

    def get_cost(self, resource_ids, days=30):
        return {rid: 32.50 for rid in resource_ids}

    def get_last_activity(self, resource_id, resource_type):
        return datetime(2026, 4, 1, tzinfo=timezone.utc)


def _text_response(
    text: str, input_tokens: int = 100, output_tokens: int = 50
) -> AIResponse:
    return AIResponse(
        stop_reason="end_turn",
        text=text,
        tool_calls=[],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _tool_response(
    tool_name: str,
    tool_id: str,
    arguments: dict,
    input_tokens: int = 150,
    output_tokens: int = 30,
) -> AIResponse:
    return AIResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=arguments)],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


ACCOUNTS = [{"id": "123456789012", "name": "test-account"}]


def _make_session(**kwargs) -> tuple[ChatSession, MagicMock]:
    fake_ai = MagicMock(spec=AIProvider)
    defaults = {
        "ai_provider": fake_ai,
        "cloud_adapter": FakeCloudAdapter(),
        "cloud": "aws",
        "accounts": ACCOUNTS,
        "ignore_regions": [],
        "budget_usd": 10.0,
    }
    defaults.update(kwargs)
    session = ChatSession(**defaults)
    return session, fake_ai


# ------------------------------------------------------------------
# Happy path
# ------------------------------------------------------------------


class TestChatHappyPath:
    def test_simple_text_response(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _text_response("Your top waste is a NAT Gateway.")

        result = session.ask("What are my top wastes?")

        assert isinstance(result, ChatResponse)
        assert result.text == "Your top waste is a NAT Gateway."
        assert result.turn_input_tokens == 100
        assert result.turn_output_tokens == 50

    def test_tool_call_then_response(self):
        session, fake_ai = _make_session()
        fake_ai.chat.side_effect = [
            _tool_response("list_resources", "tc_1", {"ignore_regions": []}),
            _text_response("Found 2 resources. The NAT Gateway costs $32.50/mo."),
        ]

        result = session.ask("Show me my resources")

        assert "NAT Gateway" in result.text
        assert fake_ai.chat.call_count == 2

    def test_multi_step_tool_calls(self):
        session, fake_ai = _make_session()
        fake_ai.chat.side_effect = [
            _tool_response("list_resources", "tc_1", {"ignore_regions": []}),
            _tool_response(
                "get_metrics",
                "tc_2",
                {"resource_id": "nat-0abc123", "resource_type": "AWS::EC2::NatGateway"},
            ),
            _text_response("The NAT Gateway is idle — only 847 bytes in 90 days."),
        ]

        result = session.ask("Is my NAT Gateway idle?")

        assert "idle" in result.text.lower()
        assert fake_ai.chat.call_count == 3
        assert result.turn_input_tokens == 150 + 150 + 100
        assert result.turn_output_tokens == 30 + 30 + 50


# ------------------------------------------------------------------
# Conversation history
# ------------------------------------------------------------------


class TestChatHistory:
    def test_history_preserved_across_turns(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _text_response("Answer 1")

        session.ask("Question 1")

        fake_ai.chat.return_value = _text_response("Answer 2")
        session.ask("Question 2")

        last_call_messages = fake_ai.chat.call_args[0][0]
        texts = [m.text for m in last_call_messages if m.text]
        assert "Question 1" in texts
        assert "Answer 1" in texts
        assert "Question 2" in texts

    def test_clear_history_resets_messages(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _text_response("Answer")

        session.ask("Question")
        assert session.is_resources_loaded is True
        assert len(session._messages) > 0

        session.clear_history()
        assert len(session._messages) == 0
        assert session.is_resources_loaded is False

    def test_history_trimming_drops_old_turns(self):
        session, fake_ai = _make_session()
        huge_text = "x" * 400_000
        fake_ai.chat.return_value = _text_response(huge_text)

        session.ask("Question 1")

        fake_ai.chat.return_value = _text_response("Short answer")
        session.ask("Question 2")

        has_context_marker = any(
            m.text and "[Context:" in m.text for m in session._messages
        )
        assert has_context_marker

    def test_history_trimming_uses_llm_summary(self):
        """When trimming, the session asks the AI for a summary of dropped messages."""
        session, fake_ai = _make_session()
        huge_text = "x" * 400_000
        fake_ai.chat.return_value = _text_response(huge_text)
        session.ask("Question about NAT Gateway")

        fake_ai.chat.side_effect = [
            _text_response("NAT Gateway nat-0abc123 costs $32.50/mo and is idle."),
            _text_response("Follow-up answer"),
        ]
        session.ask("Follow up")

        context_msgs = [
            m for m in session._messages if m.text and "[Context:" in m.text
        ]
        assert len(context_msgs) >= 1

    def test_history_trimming_falls_back_on_summary_failure(self):
        """If the summary LLM call fails, falls back to static context."""
        session, fake_ai = _make_session()
        huge_text = "x" * 400_000
        fake_ai.chat.return_value = _text_response(huge_text)
        session.ask("Question 1")

        fake_ai.chat.side_effect = RuntimeError("API down")
        try:
            session.ask("Question 2")
        except RuntimeError:
            pass

        context_msgs = [
            m for m in session._messages if m.text and "[Context:" in m.text
        ]
        assert len(context_msgs) >= 1
        static_msg = context_msgs[0].text
        assert "earlier messages were trimmed" in static_msg


# ------------------------------------------------------------------
# Budget and safety
# ------------------------------------------------------------------


class TestChatSafety:
    def test_budget_exceeded_returns_message(self):
        session, fake_ai = _make_session(budget_usd=0.0001)
        fake_ai.chat.return_value = _text_response(
            "Answer", input_tokens=50000, output_tokens=10000
        )

        result = session.ask("Expensive question")

        assert "budget" in result.text.lower()

    def test_max_tool_rounds_returns_safety_message(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _tool_response(
            "list_resources", "tc_loop", {"ignore_regions": []}
        )

        result = session.ask("Question that loops forever")

        assert "too many tool calls" in result.text.lower()
        assert fake_ai.chat.call_count == MAX_TOOL_ROUNDS

    def test_tool_error_passed_back_to_ai(self):
        adapter = FakeCloudAdapter()
        adapter.get_metrics = MagicMock(side_effect=ValueError("API timeout"))

        session, fake_ai = _make_session(cloud_adapter=adapter)
        fake_ai.chat.side_effect = [
            _tool_response(
                "get_metrics",
                "tc_err",
                {"resource_id": "nat-0abc123", "resource_type": "AWS::EC2::NatGateway"},
            ),
            _text_response(
                "I couldn't fetch metrics, but the resource costs $32.50/mo."
            ),
        ]

        result = session.ask("Check the NAT Gateway")

        assert result.text is not None
        assert fake_ai.chat.call_count == 2

        second_call_messages = fake_ai.chat.call_args_list[1][0][0]
        tool_result_msgs = [m for m in second_call_messages if m.tool_results]
        assert len(tool_result_msgs) > 0
        assert tool_result_msgs[-1].tool_results[0].is_error is True

    def test_network_error_handled_gracefully(self):
        session, fake_ai = _make_session()
        fake_ai.chat.side_effect = ConnectionError("Connection refused")

        result = session.ask("Question")

        assert "network error" in result.text.lower()

    def test_runtime_error_handled_gracefully(self):
        session, fake_ai = _make_session()
        fake_ai.chat.side_effect = RuntimeError("Retries exhausted")

        result = session.ask("Question")

        assert "ai provider error" in result.text.lower()

    def test_timeout_error_handled_gracefully(self):
        session, fake_ai = _make_session()
        fake_ai.chat.side_effect = TimeoutError("Read timed out")

        result = session.ask("Question")

        assert "network error" in result.text.lower()

    def test_parse_error_handled_gracefully(self):
        session, fake_ai = _make_session()
        fake_ai.chat.side_effect = ValueError("Invalid JSON in response")

        result = session.ask("Question")

        assert "parse" in result.text.lower()


# ------------------------------------------------------------------
# Cost tracking
# ------------------------------------------------------------------


class TestChatCostTracking:
    def test_cost_summary_accumulates(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _text_response(
            "Answer", input_tokens=200, output_tokens=100
        )

        session.ask("Q1")
        session.ask("Q2")
        session.ask("Q3")

        summary = session.cost_summary
        assert summary["total_input_tokens"] == 600
        assert summary["total_output_tokens"] == 300
        assert summary["iterations"] == 3

    def test_per_turn_cost_in_response(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _text_response(
            "Answer", input_tokens=1000, output_tokens=500
        )

        result = session.ask("Question")

        assert result.turn_input_tokens == 1000
        assert result.turn_output_tokens == 500
        assert result.turn_cost_usd > 0


# ------------------------------------------------------------------
# Resource loading
# ------------------------------------------------------------------


class TestChatResourceLoading:
    def test_resources_loaded_flag(self):
        session, fake_ai = _make_session()
        assert session.is_resources_loaded is False

        fake_ai.chat.return_value = _text_response("Answer")
        session.ask("Question")

        assert session.is_resources_loaded is True

    def test_resources_loaded_false_after_clear(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _text_response("Answer")
        session.ask("Q")
        assert session.is_resources_loaded is True

        session.clear_history()
        assert session.is_resources_loaded is False

    def test_resources_prefetched_once(self):
        session, fake_ai = _make_session()
        fake_ai.chat.return_value = _text_response("Answer")

        with patch.object(
            session._loop,
            "_prefilter_resources",
            wraps=session._loop._prefilter_resources,
        ) as mock_pf:
            session.ask("Q1")
            session.ask("Q2")
            session.ask("Q3")

            mock_pf.assert_called_once()

    def test_on_tool_call_callback_fires(self):
        calls: list[tuple[str, str]] = []

        def recorder(tool_name: str, resource_id: str) -> None:
            calls.append((tool_name, resource_id))

        session, fake_ai = _make_session(on_tool_call=recorder)
        fake_ai.chat.side_effect = [
            _tool_response(
                "get_metrics",
                "tc_1",
                {"resource_id": "nat-0abc123", "resource_type": "AWS::EC2::NatGateway"},
            ),
            _text_response("Done"),
        ]

        session.ask("Check it")

        assert len(calls) == 1
        assert calls[0] == ("get_metrics", "nat-0abc123")


# ------------------------------------------------------------------
# Prompt tests
# ------------------------------------------------------------------


class TestChatPrompts:
    def test_chat_tool_schemas_excludes_submit_findings(self):
        schemas = build_chat_tool_schemas()
        names = [s["name"] for s in schemas]
        assert len(schemas) == 4
        assert "submit_findings" not in names
        assert "list_resources" in names
        assert "get_metrics" in names
        assert "get_cost" in names
        assert "get_last_activity" in names

    def test_chat_system_prompt_contains_cloud(self):
        prompt = build_chat_system_prompt(
            cloud="aws",
            ignore_regions=[],
            accounts=[{"id": "123", "name": "test"}],
        )
        assert "AWS" in prompt

    def test_chat_prompt_has_cached_resources_note(self):
        prompt_no = build_chat_system_prompt(
            cloud="aws",
            ignore_regions=[],
            accounts=[{"id": "1", "name": "t"}],
            has_cached_resources=False,
        )
        prompt_yes = build_chat_system_prompt(
            cloud="aws",
            ignore_regions=[],
            accounts=[{"id": "1", "name": "t"}],
            has_cached_resources=True,
        )
        assert "not been loaded" in prompt_no.lower()
        assert "already been loaded" in prompt_yes.lower()

    def test_right_sizing_rules_shared(self):
        batch = build_system_prompt("aws", [], [{"id": "1", "name": "t"}])
        chat = build_chat_system_prompt("aws", [], [{"id": "1", "name": "t"}])
        assert "RIGHT-SIZING RULES" in batch
        assert "RIGHT-SIZING RULES" in chat
        assert "m5.4xlarge" in batch
        assert "m5.4xlarge" in chat
