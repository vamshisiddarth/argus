"""Unit tests for chat mode polish — format_tool_result, trim, force_summarize."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from ai.base import Message
from core.agent.chat import ChatSession, _group_into_turns

# ---------------------------------------------------------------------------
# format_tool_result — list_resources
# ---------------------------------------------------------------------------


def _make_resources(n: int) -> str:
    resources = [
        {
            "id": f"i-{i:04d}",
            "type": "AWS::EC2::Instance",
            "region": "us-east-1",
            "name": f"server-{i}",
            "cost_usd": float(100 - i),
        }
        for i in range(n)
    ]
    return json.dumps(resources)


def test_format_tool_result_list_resources_top5():
    raw = _make_resources(47)
    result = ChatSession.format_tool_result("list_resources", raw)
    assert "47 resources" in result
    assert "us-east-1" in result
    # Top costs shown
    assert "i-0000" in result or "server-0" in result
    # No raw JSON
    assert "{" not in result


def test_format_tool_result_list_resources_empty():
    result = ChatSession.format_tool_result("list_resources", "[]")
    assert "No resources found" in result


# ---------------------------------------------------------------------------
# format_tool_result — get_metrics
# ---------------------------------------------------------------------------


def _make_metrics(cpu_avg: float = 1.5, cpu_max: float = 8.0) -> str:
    data = {
        "metrics": {
            "CPUUtilization": {"avg": cpu_avg, "max": cpu_max, "min": 0.1},
            "NetworkIn": {"avg": 0, "max": 0, "min": 0},
        },
        "window_days": 14,
        "last_datapoint": "2026-06-01T10:00:00+00:00",
    }
    return json.dumps(data)


def test_format_tool_result_get_metrics_shows_stats():
    result = ChatSession.format_tool_result("get_metrics", _make_metrics())
    assert "Metrics" in result
    assert "14" in result  # window days
    assert "CPUUtilization" in result
    assert "1.5" in result
    # No raw JSON
    assert "{" not in result


def test_format_tool_result_get_metrics_idle_signal():
    result = ChatSession.format_tool_result("get_metrics", _make_metrics(cpu_avg=1.2))
    assert "idle" in result.lower()


def test_format_tool_result_get_metrics_no_data():
    raw = json.dumps({"metrics": {}, "window_days": 14})
    result = ChatSession.format_tool_result("get_metrics", raw)
    assert "No metrics" in result or "No metric" in result
    assert "14" in result


# ---------------------------------------------------------------------------
# format_tool_result — get_cost
# ---------------------------------------------------------------------------


def test_format_tool_result_get_cost_total_and_items():
    costs = {"i-0001": 128.40, "db-prod": 94.20, "vol-abc": 0.0}
    result = ChatSession.format_tool_result("get_cost", json.dumps(costs))
    assert "222.60" in result
    assert "128.40" in result
    assert "94.20" in result
    assert "$0" in result
    assert "{" not in result


def test_format_tool_result_get_cost_empty():
    result = ChatSession.format_tool_result("get_cost", "{}")
    assert "No cost data" in result


# ---------------------------------------------------------------------------
# format_tool_result — get_last_activity
# ---------------------------------------------------------------------------


def test_format_tool_result_get_last_activity_recent():
    dt = (datetime.now(tz=timezone.utc) - timedelta(days=23)).isoformat()
    result = ChatSession.format_tool_result("get_last_activity", dt)
    assert "Last activity:" in result
    assert "23 days ago" in result


def test_format_tool_result_get_last_activity_null():
    result = ChatSession.format_tool_result("get_last_activity", "null")
    assert "no record" in result
    assert "fully idle" in result


# ---------------------------------------------------------------------------
# format_tool_result — invalid JSON / unknown tool
# ---------------------------------------------------------------------------


def test_format_tool_result_invalid_json_returns_raw():
    bad = "this is not json {{{"
    result = ChatSession.format_tool_result("list_resources", bad)
    assert result == bad


def test_format_tool_result_unknown_tool_passthrough():
    raw = '{"something": "else"}'
    result = ChatSession.format_tool_result("unknown_tool", raw)
    assert result == raw


# ---------------------------------------------------------------------------
# _group_into_turns
# ---------------------------------------------------------------------------


def _user(text: str) -> Message:
    return Message(role="user", text=text)


def _assistant(text: str) -> Message:
    return Message(role="assistant", text=text)


def _tool_result() -> Message:
    from ai.base import ToolResult

    return Message(
        role="user", tool_results=[ToolResult(tool_call_id="tc1", content="x")]
    )


def test_group_into_turns_simple():
    msgs = [_user("q1"), _assistant("a1"), _user("q2"), _assistant("a2")]
    turns = _group_into_turns(msgs)
    assert len(turns) == 2
    assert turns[0] == [_user("q1"), _assistant("a1")]
    assert turns[1] == [_user("q2"), _assistant("a2")]


def test_group_into_turns_tool_result_stays_with_turn():
    tr = _tool_result()
    msgs = [_user("q1"), _assistant("a1"), tr, _user("q2"), _assistant("a2")]
    turns = _group_into_turns(msgs)
    assert len(turns) == 2
    # tool result stays in the first turn
    assert tr in turns[0]
    assert _user("q2") in turns[1]


# ---------------------------------------------------------------------------
# force_summarize
# ---------------------------------------------------------------------------


def _make_session() -> ChatSession:
    ai = MagicMock()
    ai.chat.return_value = MagicMock(
        text="Summary of earlier turns.",
        input_tokens=10,
        output_tokens=5,
        stop_reason="end_turn",
        tool_calls=[],
    )
    adapter = MagicMock()
    return ChatSession(
        ai_provider=ai,
        cloud_adapter=adapter,
        cloud="aws",
        accounts=[{"id": "123", "name": "test"}],
    )


def test_force_summarize_reduces_history():
    session = _make_session()
    # Populate 10 messages
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        session._messages.append(Message(role=role, text=f"msg {i}"))

    session.force_summarize()
    # At most 5 messages after (4 kept + 1 context summary)
    assert len(session._messages) <= 5


def test_force_summarize_noop_on_short_history():
    session = _make_session()
    session._messages = [_user("q1"), _assistant("a1")]
    session.force_summarize()
    assert len(session._messages) == 2
