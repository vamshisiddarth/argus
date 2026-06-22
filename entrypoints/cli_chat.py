"""Interactive chat REPL for Argus."""

from __future__ import annotations

import readline as _readline  # noqa: F401 — enables arrow keys and history
import sys
from typing import Any

import structlog

from core.agent.chat import ChatResponse, ChatSession
from core.log import configure_logging

logger = structlog.get_logger(__name__)

# Optional rich import — falls back to plain text if not installed.
try:
    from rich.console import Console
    from rich.status import Status  # noqa: F401

    _console = Console()
    _HAS_RICH = True
except ImportError:
    _console = None  # type: ignore[assignment]
    _HAS_RICH = False

_COMMANDS = {
    "/help": "Show available commands and example questions",
    "/scan": "Run a full batch scan (same as argus scan)",
    "/cost": "Show session token usage and cost",
    "/clear": "Clear conversation history",
    "/quit": "Exit the chat",
    "/exit": "Exit the chat",
}


def run_chat_repl(
    cloud: str,
    ai_provider_name: str,
    accounts: list[dict[str, Any]],
    ignore_regions: list[str],
    budget_usd: float,
    primary_region: str,
) -> None:
    """Start the interactive chat REPL."""
    configure_logging()

    from core.__version__ import __version__

    ai_provider = _build_ai_provider(ai_provider_name, cloud, primary_region)
    adapter = _build_adapter(cloud, primary_region)

    session = ChatSession(
        ai_provider=ai_provider,
        cloud_adapter=adapter,
        cloud=cloud,
        accounts=accounts,
        ignore_regions=ignore_regions,
        budget_usd=budget_usd,
        on_tool_call=_print_tool_status,
    )

    account_desc = ", ".join(
        f"{a.get('name', 'unnamed')} ({a.get('id', '?')})" for a in accounts
    )
    _print_banner(__version__, cloud, account_desc)

    while True:
        try:
            user_input = _read_input()
        except KeyboardInterrupt:
            print("\n(Use /quit to exit)")
            continue
        except EOFError:
            _print_dim("\nGoodbye.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "/quit", "/exit"):
            _print_dim("Goodbye.")
            break

        if user_input.startswith("/"):
            _handle_command(user_input, session, cloud)
            continue

        if not session.is_resources_loaded:
            _with_status(
                f"Fetching resources from {cloud.upper()}...", session.load_resources
            )

        response = _ask_with_status(session, user_input)
        print()
        print(response.text)
        print()
        _print_cost_footer(response, session)


def _read_input() -> str:
    """Read user input with multi-line support.

    A trailing backslash continues to the next line.
    """
    first_line = input("argus> ").strip()
    if not first_line.endswith("\\"):
        return first_line

    lines = [first_line[:-1]]
    while True:
        try:
            continuation = input("   ... ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if continuation.endswith("\\"):
            lines.append(continuation[:-1])
        else:
            lines.append(continuation)
            break
    return " ".join(lines).strip()


def _ask_with_status(session: ChatSession, user_input: str) -> ChatResponse:
    if _HAS_RICH:
        with _console.status("Thinking...", spinner="dots"):
            return session.ask(user_input)
    return session.ask(user_input)


def _with_status(message: str, fn: Any) -> None:
    if _HAS_RICH:
        with _console.status(message, spinner="dots"):
            fn()
    else:
        print(f"  {message}", file=sys.stderr)
        fn()


def _handle_command(cmd: str, session: ChatSession, cloud: str) -> None:
    cmd_lower = cmd.lower().split()[0]

    match cmd_lower:
        case "/help":
            print("\nAvailable commands:")
            for name, desc in _COMMANDS.items():
                print(f"  {name:10s} {desc}")
            print("\nExample questions:")
            print('  "What are my top 3 wastes?"')
            print('  "Is my NAT Gateway idle?"')
            print('  "How much would I save by deleting unused EBS volumes?"')
            print("\nTip: End a line with \\ to continue on the next line.")
            print()

        case "/cost":
            summary = session.cost_summary
            _print_cost_summary(summary)

        case "/clear":
            session.clear_history()
            print("Conversation history cleared.\n")

        case "/scan":
            print(
                f"To run a full batch scan, open another terminal and run:\n"
                f"  argus scan --cloud {cloud}\n"
            )

        case _:
            print(
                f"Unknown command: {cmd_lower}. "
                f"Type /help for available commands.\n"
            )


def _print_banner(version: str, cloud: str, account_desc: str) -> None:
    if _HAS_RICH:
        _console.print(
            f"[bold]Argus v{version}[/bold] — Interactive Cloud Cost Assistant"
        )
        _console.print(
            f"Cloud: [cyan]{cloud.upper()}[/cyan] | Accounts: {account_desc}"
        )
        _console.print("Type your question, or /help for commands.\n")
    else:
        print(f"Argus v{version} — Interactive Cloud Cost Assistant")
        print(f"Cloud: {cloud.upper()} | Accounts: {account_desc}")
        print("Type your question, or /help for commands.\n")


def _print_tool_status(tool_name: str, resource_id: str) -> None:
    label = tool_name.replace("_", " ").title()
    msg = f"  {label}: {resource_id}..." if resource_id else f"  {label}..."
    if _HAS_RICH:
        _console.print(f"[dim]{msg}[/dim]", highlight=False)
    else:
        print(msg, file=sys.stderr)


def _print_cost_footer(response: ChatResponse, session: ChatSession) -> None:
    summary = session.cost_summary
    line = (
        f"[this turn: {response.turn_input_tokens:,} in / "
        f"{response.turn_output_tokens:,} out, "
        f"${response.turn_cost_usd:.4f} | "
        f"session: {summary['total_input_tokens']:,} in / "
        f"{summary['total_output_tokens']:,} out, "
        f"${summary['estimated_cost_usd']:.4f} / "
        f"${summary['budget_usd']:.2f} budget]"
    )
    if _HAS_RICH:
        _console.print(f"[dim]{line}[/dim]", highlight=False)
    else:
        print(line)
    print()


def _print_cost_summary(summary: dict[str, Any]) -> None:
    line = (
        f"\nSession cost: "
        f"{summary['total_input_tokens']:,} in / "
        f"{summary['total_output_tokens']:,} out | "
        f"${summary['estimated_cost_usd']:.4f} / "
        f"${summary['budget_usd']:.2f} budget\n"
    )
    if _HAS_RICH:
        _console.print(f"[bold]{line}[/bold]", highlight=False)
    else:
        print(line)


def _print_dim(text: str) -> None:
    if _HAS_RICH:
        _console.print(f"[dim]{text}[/dim]", highlight=False)
    else:
        print(text)


def _build_ai_provider(provider_name: str, cloud: str, primary_region: str) -> Any:
    match provider_name:
        case "anthropic":
            from ai.anthropic import AnthropicProvider

            return AnthropicProvider()
        case "bedrock":
            from ai.bedrock import BedrockProvider

            return BedrockProvider(region=primary_region)
        case "vertexai":
            import os

            from ai.vertexai import VertexAIProvider

            return VertexAIProvider(
                project=os.environ.get("VERTEXAI_PROJECT", ""),
                location=os.environ.get("VERTEXAI_LOCATION", "us-central1"),
            )
        case "azure_openai":
            from ai.azure_openai import AzureOpenAIProvider

            return AzureOpenAIProvider()
        case _:
            from ai.anthropic import AnthropicProvider

            return AnthropicProvider()


def _build_adapter(cloud: str, primary_region: str) -> Any:
    match cloud:
        case "aws":
            from adapters.aws.adapter import AWSAdapter

            return AWSAdapter.for_account(account=None, region=primary_region)
        case "gcp":
            from adapters.gcp.adapter import GCPAdapter

            return GCPAdapter.from_env()
        case "azure":
            from adapters.azure.adapter import AzureAdapter

            return AzureAdapter.from_env()
        case _:
            raise ValueError(f"Unsupported cloud: {cloud}")
