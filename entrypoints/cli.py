"""
CLI entrypoint for Argus.
Runs the same agent loop as the Lambda handler, but from a local terminal.

Usage:
  python main.py --cloud aws --run-now
  python main.py --cloud aws --run-now --dry-run --ignore-regions ap-east-1,me-south-1
  python main.py --cloud aws --run-now --ai-provider anthropic
  python main.py --cloud aws --run-now --accounts accounts.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Argus — AI-powered cloud cost optimization agent",
    )
    parser.add_argument(
        "--cloud",
        default="aws",
        choices=["aws", "gcp", "azure"],
        help="Cloud provider to scan (default: aws)",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        required=True,
        help="Trigger a scan immediately",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log the Slack payload instead of posting it",
    )
    parser.add_argument(
        "--ignore-regions",
        default=os.environ.get("IGNORE_REGIONS", ""),
        dest="ignore_regions",
        metavar="REGIONS",
        help=(
            "Comma-separated regions to exclude from the scan "
            "(default: none, scan all)"
        ),
    )
    parser.add_argument(
        "--primary-region",
        default=os.environ.get("PRIMARY_REGION", "us-east-1"),
        dest="primary_region",
        help="AWS region for the boto3 session and Bedrock calls (default: us-east-1)",
    )
    parser.add_argument(
        "--ai-provider",
        default=os.environ.get("AI_PROVIDER", "anthropic"),
        choices=["anthropic", "bedrock", "vertexai", "azure_openai"],
        help="AI provider (default: anthropic — requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--accounts",
        metavar="PATH",
        help="Path to accounts.yaml for multi-account mode",
    )

    args = parser.parse_args(argv)

    # Propagate CLI args as env vars so the Lambda handler can read them.
    os.environ["IGNORE_REGIONS"] = args.ignore_regions
    os.environ["PRIMARY_REGION"] = args.primary_region
    os.environ["AI_PROVIDER"] = args.ai_provider
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"

    if args.accounts:
        _apply_accounts_config(args.accounts)

    if args.cloud == "aws":
        from entrypoints.aws_lambda import handler

        result = handler({}, None)
    elif args.cloud == "gcp":
        from entrypoints.gcp_cloudrun import main as gcp_main

        result = gcp_main()
    elif args.cloud == "azure":
        from entrypoints.azure_function import main as azure_main

        result = azure_main(None)
    else:
        print(f"Cloud {args.cloud!r} is not supported.", file=sys.stderr)
        sys.exit(1)

    if result is not None:
        print(json.dumps(result, indent=2))


def _apply_accounts_config(path: str) -> None:
    """Load accounts.yaml and set ACCOUNTS_MODE + ACCOUNTS_CONFIG env vars."""
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
        accounts = config.get("accounts", [])
        os.environ["ACCOUNTS_CONFIG"] = json.dumps(accounts)
