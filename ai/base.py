from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool invocation requested by the AI."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The result of executing a tool call."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """
    A single turn in the agent conversation.
    role: "user" | "assistant"
    Exactly one of text, tool_calls, or tool_results will be populated.
    """

    role: str
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class Tool:
    """Definition of a tool the AI can call."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class AIResponse:
    """Parsed response from an AI provider."""

    stop_reason: str  # "tool_use" | "end_turn" | "max_tokens"
    text: str | None
    tool_calls: list[ToolCall]


class AIProvider(ABC):
    """
    Abstract AI provider. One implementation per model family.
    The agent loop only ever calls chat() — never raw SDK methods.
    """

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system_prompt: str | None = None,
    ) -> AIResponse:
        """
        Send the conversation to the AI and get a response.
        system_prompt is passed separately so each provider can handle it
        in the way their API expects (e.g. Anthropic has a dedicated system param).
        """
        ...
