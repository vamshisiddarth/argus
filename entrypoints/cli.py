"""
CLI entrypoint for Argus.

Usage:
  argus scan --cloud aws
  argus scan --cloud gcp --dry-run
  argus chat --cloud azure --ai-provider azure_openai

  # Auto-detect cloud from environment:
  argus scan          # detects from GCP_PROJECT_ID / AZURE_SUBSCRIPTION_IDS / AWS creds

  # Backward compat (same as argus scan):
  argus --run-now --cloud aws
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _detect_cloud() -> str | None:
    """Infer cloud provider from environment variables.

    Returns the detected cloud name, or None if ambiguous/undetectable.
    Checked in order: GCP, Azure, AWS — GCP and Azure require explicit
    env vars, while AWS credentials are often present by default.
    """
    if os.environ.get("GCP_PROJECT_ID"):
        return "gcp"
    if os.environ.get("AZURE_SUBSCRIPTION_IDS"):
        return "azure"
    if any(
        os.environ.get(k)
        for k in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_DEFAULT_REGION")
    ):
        return "aws"
    return None


def main(argv: list[str] | None = None) -> None:
    from core.__version__ import __version__

    parser = argparse.ArgumentParser(
        prog="argus",
        description="Argus — AI-powered cloud cost optimization agent",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Backward compat: same as 'argus scan'",
    )
    parser.add_argument(
        "--cloud",
        default=None,
        choices=["aws", "gcp", "azure"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--ignore-regions",
        default=None,
        dest="ignore_regions",
        metavar="REGIONS",
    )
    parser.add_argument(
        "--primary-region",
        default=None,
        dest="primary_region",
    )
    parser.add_argument(
        "--ai-provider",
        default=None,
        choices=["anthropic", "bedrock", "vertexai", "azure_openai"],
    )
    parser.add_argument("--accounts", metavar="PATH")
    parser.add_argument(
        "--max-resources",
        default=None,
        dest="max_resources",
        type=int,
        metavar="N",
    )
    parser.add_argument(
        "--lookback-days",
        default=None,
        dest="lookback_days",
        type=int,
        metavar="DAYS",
    )
    parser.add_argument(
        "--llm-budget",
        default=None,
        dest="llm_budget",
        type=float,
        metavar="USD",
    )

    subparsers = parser.add_subparsers(dest="command")

    # --- argus scan ---
    scan_parser = subparsers.add_parser(
        "scan", help="Run a full cost optimization scan"
    )
    scan_parser.add_argument(
        "--cloud",
        default=None,
        choices=["aws", "gcp", "azure"],
        help="Cloud provider (auto-detected from env vars if omitted)",
    )
    scan_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log the Slack payload instead of posting it",
    )
    scan_parser.add_argument(
        "--ignore-regions",
        default=os.environ.get("IGNORE_REGIONS", ""),
        dest="ignore_regions",
        metavar="REGIONS",
        help="Comma-separated regions to exclude (default: none)",
    )
    scan_parser.add_argument(
        "--primary-region",
        default=os.environ.get("PRIMARY_REGION", "us-east-1"),
        dest="primary_region",
        help="AWS region for boto3/Bedrock (default: us-east-1)",
    )
    scan_parser.add_argument(
        "--ai-provider",
        default=os.environ.get("AI_PROVIDER", "anthropic"),
        choices=["anthropic", "bedrock", "vertexai", "azure_openai"],
        help="AI provider (default: anthropic)",
    )
    scan_parser.add_argument(
        "--accounts",
        metavar="PATH",
        help="Path to accounts.yaml for multi-account mode",
    )
    scan_parser.add_argument(
        "--max-resources",
        default=os.environ.get("MAX_RESOURCES_PER_SCAN", "200"),
        dest="max_resources",
        type=int,
        metavar="N",
        help="Max resources to analyze per scan (default: 200)",
    )
    scan_parser.add_argument(
        "--lookback-days",
        default=os.environ.get("METRICS_LOOKBACK_DAYS", "90"),
        dest="lookback_days",
        type=int,
        metavar="DAYS",
        help="Metrics lookback window in days (default: 90)",
    )
    scan_parser.add_argument(
        "--llm-budget",
        default=os.environ.get("LLM_BUDGET_USD", "2.0"),
        dest="llm_budget",
        type=float,
        metavar="USD",
        help="LLM cost budget per scan in USD (default: 2.00, 0=unlimited)",
    )

    # --- argus chat ---
    chat_parser = subparsers.add_parser("chat", help="Interactive cloud cost Q&A")
    chat_parser.add_argument(
        "--cloud",
        default=None,
        choices=["aws", "gcp", "azure"],
        help="Cloud provider (auto-detected from env vars if omitted)",
    )
    chat_parser.add_argument(
        "--ignore-regions",
        default=os.environ.get("IGNORE_REGIONS", ""),
        dest="ignore_regions",
        metavar="REGIONS",
        help="Comma-separated regions to exclude (default: none)",
    )
    chat_parser.add_argument(
        "--primary-region",
        default=os.environ.get("PRIMARY_REGION", "us-east-1"),
        dest="primary_region",
        help="AWS region for boto3/Bedrock (default: us-east-1)",
    )
    chat_parser.add_argument(
        "--ai-provider",
        default=os.environ.get("AI_PROVIDER", "anthropic"),
        choices=["anthropic", "bedrock", "vertexai", "azure_openai"],
        help="AI provider (default: anthropic)",
    )
    chat_parser.add_argument(
        "--accounts",
        metavar="PATH",
        help="Path to accounts.yaml for multi-account mode",
    )
    chat_parser.add_argument(
        "--llm-budget",
        default=os.environ.get("LLM_BUDGET_USD", "1.0"),
        dest="llm_budget",
        type=float,
        metavar="USD",
        help="Session cost budget in USD (default: 1.00, 0=unlimited)",
    )

    args = parser.parse_args(argv)

    # Backward compat: argus --run-now --cloud aws → treat as scan
    if args.run_now and not args.command:
        args.command = "scan"
        if args.ignore_regions is None:
            args.ignore_regions = os.environ.get("IGNORE_REGIONS", "")
        if args.primary_region is None:
            args.primary_region = os.environ.get("PRIMARY_REGION", "us-east-1")
        if args.ai_provider is None:
            args.ai_provider = os.environ.get("AI_PROVIDER", "anthropic")
        if args.max_resources is None:
            args.max_resources = int(os.environ.get("MAX_RESOURCES_PER_SCAN", "200"))
        if args.lookback_days is None:
            args.lookback_days = int(os.environ.get("METRICS_LOOKBACK_DAYS", "90"))
        if args.llm_budget is None:
            args.llm_budget = float(os.environ.get("LLM_BUDGET_USD", "2.0"))

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Auto-detect cloud from env vars if not specified
    if args.cloud is None:
        detected = _detect_cloud()
        if detected:
            args.cloud = detected
            print(f"Auto-detected cloud: {detected}", file=sys.stderr)
        else:
            print(
                "Could not detect cloud provider. Set --cloud or configure"
                " GCP_PROJECT_ID / AZURE_SUBSCRIPTION_IDS / AWS credentials.",
                file=sys.stderr,
            )
            sys.exit(1)

    if args.command == "scan":
        _run_scan(args)
    elif args.command == "chat":
        _run_chat(args)


# ---------------------------------------------------------------------------
# Cloud auto-detection (for --cloud, only used above via _detect_cloud)
# ---------------------------------------------------------------------------


def _run_scan(args: argparse.Namespace) -> None:
    os.environ["IGNORE_REGIONS"] = args.ignore_regions
    os.environ["PRIMARY_REGION"] = args.primary_region
    os.environ["AI_PROVIDER"] = args.ai_provider
    os.environ["MAX_RESOURCES_PER_SCAN"] = str(args.max_resources)
    os.environ["METRICS_LOOKBACK_DAYS"] = str(args.lookback_days)
    os.environ["LLM_BUDGET_USD"] = str(args.llm_budget)
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"

    if args.accounts:
        _apply_accounts_config(args.accounts, args.cloud)

    if args.cloud == "aws":
        from entrypoints.aws_lambda import handler

        result = handler({}, None)
    elif args.cloud == "gcp":
        from entrypoints.gcp_cloudrun import main as gcp_main

        result = gcp_main()  # type: ignore[assignment,func-returns-value]
    elif args.cloud == "azure":
        from entrypoints.azure_function import main as azure_main

        result = azure_main(None)  # type: ignore[assignment,func-returns-value]
    else:
        print(f"Cloud {args.cloud!r} is not supported.", file=sys.stderr)
        sys.exit(1)

    if result is not None:
        print(json.dumps(result, indent=2))


def _run_chat(args: argparse.Namespace) -> None:
    os.environ["PRIMARY_REGION"] = args.primary_region
    os.environ["AI_PROVIDER"] = args.ai_provider
    if args.accounts:
        _apply_accounts_config(args.accounts, args.cloud)

    ignore_regions = [r.strip() for r in args.ignore_regions.split(",") if r.strip()]
    accounts = _resolve_accounts(args.cloud)

    from entrypoints.cli_chat import run_chat_repl

    run_chat_repl(
        cloud=args.cloud,
        ai_provider_name=args.ai_provider,
        accounts=accounts,
        ignore_regions=ignore_regions,
        budget_usd=args.llm_budget,
        primary_region=args.primary_region,
    )


def _resolve_accounts(cloud: str) -> list[dict[str, str]]:
    """Build the accounts list from env vars / config."""
    mode = os.environ.get("ACCOUNTS_MODE", "single")
    if mode == "multi":
        raw = os.environ.get("ACCOUNTS_CONFIG", "[]")
        return list(json.loads(raw))

    if cloud == "aws":
        try:
            import boto3

            sts = boto3.client("sts")
            identity = sts.get_caller_identity()
            return [{"id": identity["Account"], "name": identity["Account"]}]
        except Exception:  # noqa: BLE001
            return [{"id": "unknown", "name": "current-account"}]
    elif cloud == "gcp":
        multi = os.environ.get("GCP_PROJECT_IDS", "").strip()
        if multi:
            return [
                {"id": p.strip(), "name": p.strip()}
                for p in multi.split(",")
                if p.strip()
            ]
        project = os.environ.get("GCP_PROJECT_ID", "unknown")
        return [{"id": project, "name": project}]
    elif cloud == "azure":
        subs = os.environ.get("AZURE_SUBSCRIPTION_IDS", "unknown")
        return [
            {"id": s.strip(), "name": s.strip()} for s in subs.split(",") if s.strip()
        ]
    return [{"id": "unknown", "name": "unknown"}]


def _apply_accounts_config(path: str, cloud: str) -> None:
    """Load accounts.yaml and set env vars for multi-account/project/subscription mode.

    AWS  → reads ``accounts`` key, sets ACCOUNTS_CONFIG
    GCP  → reads ``projects`` key, sets GCP_PROJECT_IDS + ACCOUNTS_CONFIG
    Azure → reads ``subscriptions`` key, sets AZURE_SUBSCRIPTION_IDS + ACCOUNTS_CONFIG
    """
    try:
        import yaml  # PyYAML — in requirements.txt
    except ImportError:
        print(
            "PyYAML is required for --accounts. Run: pip install pyyaml",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(path) as fh:
        config = yaml.safe_load(fh)

    mode = config.get("mode", "single")
    os.environ["ACCOUNTS_MODE"] = mode

    if mode == "multi":
        if cloud == "gcp":
            entries = config.get("projects", [])
            if entries:
                os.environ["GCP_PROJECT_IDS"] = ",".join(e["id"] for e in entries)
                os.environ["ACCOUNTS_CONFIG"] = json.dumps(entries)
        elif cloud == "azure":
            entries = config.get("subscriptions", [])
            if entries:
                os.environ["AZURE_SUBSCRIPTION_IDS"] = ",".join(
                    e["id"] for e in entries
                )
                os.environ["ACCOUNTS_CONFIG"] = json.dumps(entries)
        else:
            accounts = config.get("accounts", [])
            os.environ["ACCOUNTS_CONFIG"] = json.dumps(accounts)
