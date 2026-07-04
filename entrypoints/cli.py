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

# ---------------------------------------------------------------------------
# Minimal ANSI color helper (no dependencies, TTY-aware)
# ---------------------------------------------------------------------------

_IS_TTY = sys.stdout.isatty()

_RED = "\033[31m" if _IS_TTY else ""
_GREEN = "\033[32m" if _IS_TTY else ""
_YELLOW = "\033[33m" if _IS_TTY else ""
_BOLD = "\033[1m" if _IS_TTY else ""
_RESET = "\033[0m" if _IS_TTY else ""


def _ok(s: str) -> str:
    return f"{_GREEN}{s}{_RESET}"


def _err(s: str) -> str:
    return f"{_RED}{s}{_RESET}"


def _warn(s: str) -> str:
    return f"{_YELLOW}{s}{_RESET}"


def _bold(s: str) -> str:
    return f"{_BOLD}{s}{_RESET}"


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
        description="Argus — AI Cloud Detective for AWS, GCP, and Azure",
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

    # --- argus policies ---
    policies_parser = subparsers.add_parser(
        "policies",
        help="Manage and validate remediation policies",
        description=(
            "Manage Argus remediation policies.\n\n"
            "Subcommands:\n"
            "  validate   Check policy files for schema errors and conflicts\n"
            "  plan       Preview which findings would trigger Jira tickets\n"
            "  apply      Same as plan — add --confirm to create tickets (Phase 3)\n"
            "  docs       Show registry metadata: conditions and actions per type\n\n"
            "Example workflow:\n"
            "  argus policies validate --dir ./config/policies\n"
            "  argus policies plan --dir ./config/policies --report scan.json\n"
            "  argus policies docs AWS::RDS::DBInstance"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    policies_sub = policies_parser.add_subparsers(dest="policies_command")

    # argus policies validate
    pol_validate = policies_sub.add_parser(
        "validate",
        help="Validate policy files — schema + conflict detection (use as CI gate)",
    )
    pol_validate.add_argument(
        "--dir",
        default=os.environ.get("ARGUS_POLICIES_DIR", "./config/policies"),
        dest="policies_dir",
        metavar="DIR",
        help="Directory containing policy YAML files (default: ./config/policies)",
    )

    # argus policies plan
    pol_plan = policies_sub.add_parser(
        "plan",
        help="Dry-run: show which findings would match policies (no tickets created)",
    )
    pol_plan.add_argument(
        "--dir",
        default=os.environ.get("ARGUS_POLICIES_DIR", "./config/policies"),
        dest="policies_dir",
        metavar="DIR",
        help="Directory containing policy YAML files (default: ./config/policies)",
    )
    pol_plan.add_argument(
        "--report",
        default=None,
        dest="report_path",
        metavar="PATH",
        help="Path to existing scan report JSON (fast, no cloud API calls)",
    )
    pol_plan.add_argument(
        "--live",
        action="store_true",
        help="Run a live scan instead of using --report (slower, incurs API costs)",
    )
    pol_plan.add_argument(
        "--cloud",
        default=None,
        choices=["aws", "gcp", "azure"],
        help="Cloud provider — required when --live is set",
    )

    # argus policies apply
    pol_apply = policies_sub.add_parser(
        "apply",
        help="Create Jira tickets for matched findings (dry-run by default)",
    )
    pol_apply.add_argument(
        "--dir",
        default=os.environ.get("ARGUS_POLICIES_DIR", "./config/policies"),
        dest="policies_dir",
        metavar="DIR",
        help="Directory containing policy YAML files (default: ./config/policies)",
    )
    pol_apply.add_argument(
        "--report",
        default=None,
        dest="report_path",
        metavar="PATH",
        help="Path to existing scan report JSON",
    )
    pol_apply.add_argument(
        "--live",
        action="store_true",
        help="Run a live scan instead of using --report",
    )
    pol_apply.add_argument(
        "--cloud",
        default=None,
        choices=["aws", "gcp", "azure"],
        help="Cloud provider — required when --live is set",
    )
    pol_apply.add_argument(
        "--confirm",
        action="store_true",
        help="Actually create Jira tickets (omit for dry-run)",
    )

    # argus policies docs
    pol_docs = policies_sub.add_parser(
        "docs",
        help="Show registry metadata, valid metrics, and valid actions per type",
    )
    pol_docs.add_argument(
        "resource_type",
        nargs="?",
        default=None,
        metavar="RESOURCE_TYPE",
        help="e.g. AWS::RDS::DBInstance (omit to list all known types)",
    )
    pol_docs.add_argument(
        "--cloud",
        default=None,
        choices=["aws", "gcp", "azure"],
        help="Filter listed types by cloud (only applies when no resource_type given)",
    )

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

    # policies subcommands don't require a cloud provider
    if args.command == "policies":
        if not hasattr(args, "policies_command") or not args.policies_command:
            policies_parser.print_help()
            sys.exit(0)
        if args.policies_command == "validate":
            sys.exit(_run_policies_validate(args))
        elif args.policies_command == "plan":
            sys.exit(_run_policies_plan(args, confirm=False))
        elif args.policies_command == "apply":
            sys.exit(_run_policies_plan(args, confirm=args.confirm))
        elif args.policies_command == "docs":
            _run_policies_docs(args)
        return

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
    if isinstance(result, dict) and result.get("budget_exceeded"):
        sys.exit(2)


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


# ---------------------------------------------------------------------------
# argus policies validate
# ---------------------------------------------------------------------------


def _run_policies_validate(args: argparse.Namespace) -> int:
    """Returns 0 (ok/warnings only) or 1 (errors)."""
    from core.remediation.loader import PolicyLoadError, load_policies
    from core.remediation.validator import validate_policies

    policies_dir = args.policies_dir

    try:
        policies = load_policies(policies_dir)
    except PolicyLoadError as exc:
        # PolicyLoadError from load() bundles all per-file errors.
        # Print each bullet on its own line with ✗ prefix for clarity.
        print()
        for line in str(exc).splitlines():
            stripped = line.strip()
            if stripped.startswith("•"):
                print(_err(f"  ✗ {stripped[1:].strip()}"))
            elif stripped:
                print(f"  {stripped}")
        print()
        return 1

    if not policies:
        print(_warn(f"\n⚠  No policy files found in {policies_dir!r}.\n"))
        return 0

    result = validate_policies(policies)

    # Per-file summary line
    seen_files: dict[str, list] = {}
    for p in policies:
        seen_files.setdefault(p.source_file, []).append(p)

    print()
    for source_file, file_policies in sorted(seen_files.items()):
        fname = os.path.basename(source_file)
        file_errors = [e for e in result.errors if fname in e or source_file in e]
        file_warnings = [w for w in result.warnings if fname in w or source_file in w]
        for p in file_policies:
            if file_errors:
                marker = _err("✗")
                fname_col = _err(f"{fname:<30}")
            elif file_warnings:
                marker = _warn("⚠")
                fname_col = _warn(f"{fname:<30}")
            else:
                marker = _ok("✓")
                fname_col = f"{fname:<30}"
            print(
                f"  {marker} {fname_col}  weight: {p.weight:<4}  "
                f"resource: {p.resource_type}"
            )

    # Errors section
    if result.errors:
        print()
        for err in result.errors:
            # err format: "filename.yaml: <message>" or "filename.yaml:3:1: <message>"
            # Split at first ': ' to separate file ref from message
            if ": " in err:
                file_ref, _, msg = err.partition(": ")
                print(f"  {_err('✗')} {_bold(file_ref)}: {msg}")
                # Emit a targeted tip when the message names a field
                if "field" in msg or "'" in msg:
                    # Extract first quoted token as the field name hint
                    import re as _re
                    fields = _re.findall(r"'([^']+)'", msg)
                    if fields:
                        print(
                            f"     {_warn('Tip:')} Check the "
                            f"'{fields[0]}' field in {file_ref}"
                        )
            else:
                print(f"  {_err('✗')} {err}")

    # Warnings section
    if result.warnings:
        print()
        for warn in result.warnings:
            if ": " in warn:
                file_ref, _, msg = warn.partition(": ")
                print(f"  {_warn('⚠')}  {_bold(file_ref)}: {msg}")
            else:
                print(f"  {_warn('⚠')}  {warn}")

    # Summary line
    n_err = len(result.errors)
    n_warn = len(result.warnings)
    total = len(policies)
    polword = "policy" if total == 1 else "policies"
    errword = _err(f"{n_err} error(s)") if n_err else f"{n_err} error(s)"
    warnword = _warn(f"{n_warn} warning(s)") if n_warn else f"{n_warn} warning(s)"
    print(f"\n{total} {polword} loaded — {errword}, {warnword}.")

    if n_err:
        print(f"{_err('Fix errors before using policies.')}\n")
        return 1

    if n_warn:
        print("Warnings are non-blocking but should be reviewed.\n")

    return 0


# ---------------------------------------------------------------------------
# argus policies plan / apply (shared logic, confirm flag distinguishes them)
# ---------------------------------------------------------------------------


def _load_findings_from_report(report_path: str) -> list:
    """Load ResourceFinding objects from a saved scan report JSON."""
    from datetime import datetime, timezone

    from core.models.finding import ResourceFinding

    with open(report_path) as fh:
        report = json.load(fh)

    findings = []
    for raw in report.get("findings", []):
        findings.append(
            ResourceFinding(
                resource_id=raw["resource_id"],
                resource_type=raw["resource_type"],
                cloud=raw.get("cloud", "unknown"),
                region=raw.get("region", "unknown"),
                name=raw.get("name"),
                estimated_monthly_cost=float(raw.get("estimated_monthly_cost", 0.0)),
                waste_reason=raw.get("waste_reason", ""),
                recommendation=raw.get("recommendation", ""),
                priority=raw.get("priority", "low"),
                metrics_summary=raw.get("metrics_summary") or {},
                tags=raw.get("tags") or {},
                last_activity=(
                    datetime.fromisoformat(raw["last_activity"])
                    if raw.get("last_activity")
                    else None
                ),
                scan_time=datetime.now(tz=timezone.utc),
            )
        )
    return findings


def _run_policies_plan(args: argparse.Namespace, *, confirm: bool) -> int:
    """Shared logic for plan (confirm=False) and apply (confirm=True/False)."""
    from core.remediation.engine import evaluate
    from core.remediation.loader import PolicyLoadError, load_policies
    from core.remediation.validator import validate_policies

    # --- load policies ---
    try:
        policies = load_policies(args.policies_dir)
    except PolicyLoadError as exc:
        print(f"\n✗ Failed to load policies:\n  {exc}\n")
        return 1

    if not policies:
        print(f"\n⚠  No policies found in {args.policies_dir!r}. Nothing to do.\n")
        return 0

    result = validate_policies(policies)
    if not result.ok:
        print("\n✗ Policies have errors — fix them before running plan/apply:\n")
        for err in result.errors:
            print(f"  {err}\n")
        return 1
    for warn in result.warnings:
        print(f"  ⚠  WARNING: {warn}\n")

    # --- load findings ---
    if args.report_path:
        try:
            findings = _load_findings_from_report(args.report_path)
        except Exception as exc:  # noqa: BLE001
            print(f"\n✗ Failed to load report {args.report_path!r}: {exc}\n")
            return 1
        source_label = os.path.basename(args.report_path)
    elif args.live:
        if not args.cloud:
            print("\n✗ --live requires --cloud (aws | gcp | azure).\n")
            return 1
        print(f"\nRunning live scan on {args.cloud.upper()}...")
        findings = _run_live_scan_for_plan(args)
        source_label = f"live {args.cloud.upper()} scan"
    else:
        print(
            "\n✗ Specify --report PATH (fast) or --live --cloud CLOUD (live scan).\n"
        )
        return 1

    # --- evaluate ---
    proposals = evaluate(findings, policies)

    _print_plan(findings, policies, proposals, source_label, confirm=confirm)
    return 0


def _run_live_scan_for_plan(args: argparse.Namespace) -> list:
    """Trigger a minimal scan and return findings without delivering a report."""
    import tempfile


    # Reuse scan machinery via entrypoint — capture findings only
    cloud = args.cloud
    os.environ.setdefault("AI_PROVIDER", "anthropic")
    os.environ.setdefault("DRY_RUN", "true")

    if cloud == "aws":
        from entrypoints.aws_lambda import handler

        result = handler({}, None) or {}
    elif cloud == "gcp":
        from entrypoints.gcp_cloudrun import main as gcp_main

        result = gcp_main() or {}  # type: ignore[assignment]
    elif cloud == "azure":
        from entrypoints.azure_function import main as azure_main

        result = azure_main(None) or {}  # type: ignore[assignment]
    else:
        return []

    # Deserialise findings from the result dict
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    )
    json.dump(result, tmp)
    tmp.close()
    return _load_findings_from_report(tmp.name)


def _print_plan(
    findings: list,
    policies: list,
    proposals: list,
    source_label: str,
    *,
    confirm: bool,
) -> None:
    from datetime import date

    width = 69

    print(f"\nLoaded {len(policies)} polic{'y' if len(policies) == 1 else 'ies'}"
          f" from {policies[0].source_file if policies else '.'}")
    print()
    print("┌" + "─" * width + "┐")
    verb = "APPLY" if confirm else "PLAN"
    title = f" POLICY {verb} — {source_label} — {date.today()} "
    print(f"│{title:^{width}}│")
    summary = (
        f" {len(findings)} finding(s) · {len(policies)} polic"
        f"{'y' if len(policies) == 1 else 'ies'} · "
        f"{len(proposals)} match(es) "
    )
    print(f"│{summary:^{width}}│")
    print("└" + "─" * width + "┘")

    if not proposals:
        print(_warn("\n  No findings matched any policy.\n"))
        return

    for proposal in proposals:
        f = proposal.finding
        p = proposal.policy
        print(f"\n  {_ok('MATCH')}  {_bold(p.policy_id)} (weight: {p.weight})")
        resource_label = f"{f.name or f.resource_id} · {f.resource_type}"
        print(f"    Resource : {resource_label} · {f.region}")
        print(f"    Cost     : ${f.estimated_monthly_cost:.2f}/mo")
        print(f"    AI says  : \"{f.waste_reason[:80]}\"")
        print(f"    Action   : {_bold(p.action)}")
        approvers_str = ", ".join(p.approvers) if p.approvers else "(none)"
        print(f"    Approvers: {approvers_str}")

    unmatched = [p for p in policies if not any(
        prop.policy.policy_id == p.policy_id for prop in proposals
    )]
    for p in unmatched:
        print(f"\n  {_warn('NO MATCH')}  {p.policy_id} (weight: {p.weight})")
        print("    Reason   : no findings matched conditions/scope")

    print()
    print("─" * (width + 2))
    if confirm:
        print(f"  {_bold('Creating')} {len(proposals)} Jira ticket(s).")
        print(_warn("\n  Tickets would be created here in Phase 3.\n"))
    else:
        print(
            f"  {_bold('Would create')} {len(proposals)} Jira ticket(s).  "
            "No changes made."
        )
        print(
            f"\n  {_warn('Next step:')} Run with --confirm to create "
            "Jira tickets (Phase 3)\n"
        )


# ---------------------------------------------------------------------------
# argus policies docs
# ---------------------------------------------------------------------------


def _run_policies_docs(args: argparse.Namespace) -> None:
    from core.registry import get_registry

    registry = get_registry()

    if args.resource_type:
        spec = registry.get(args.resource_type)
        if spec is None:
            print(
                f"\n  Unknown resource type: {args.resource_type!r}\n"
                f"  Run 'argus policies docs' (no argument) to list all known types.\n"
            )
            return
        _print_resource_docs(spec)
        return

    # List all known types, grouped by cloud
    type_ids = registry.all_type_ids()
    if args.cloud:
        all_specs = registry.all_for_cloud(args.cloud)
    else:
        all_specs = [registry.get(tid) for tid in type_ids if registry.get(tid)]

    by_cloud: dict[str, list] = {}
    for spec in sorted(all_specs, key=lambda s: (s.cloud, s.type_id)):
        by_cloud.setdefault(spec.cloud, []).append(spec)

    if not by_cloud:
        print("\n  No resource types found.\n")
        return

    print()
    for cloud, specs in sorted(by_cloud.items()):
        print(f"  {cloud.upper()}  ({len(specs)} types)")
        print(f"  {'─' * 70}")
        print(f"    {'Resource Type':<45}  {'Display Name':<28}  Actions")
        print(f"    {'─'*45}  {'─'*28}  {'─'*20}")
        for spec in specs:
            actions = ", ".join(spec.actions) if spec.actions else "—"
            print(f"    {spec.type_id:<45}  {spec.display_name:<28}  {actions}")
        print()

    print(f"  {len(all_specs)} resource types known to registry.")
    print("  Use 'argus policies docs <TYPE>' for conditions, metrics, and actions.\n")


def _print_resource_docs(spec: object) -> None:
    type_id = spec.type_id  # type: ignore[attr-defined]
    display_name = spec.display_name  # type: ignore[attr-defined]
    cloud = spec.cloud  # type: ignore[attr-defined]
    sep = "─" * 62

    print()
    print(f"  ┌{sep}┐")
    print(f"  │  {type_id:<60}│")
    print(f"  │  {display_name:<60}│")
    print(f"  │  cloud: {cloud:<53}│")
    print(f"  └{sep}┘")
    print()

    # Tier 1 — universal conditions
    print(_bold("  ▸ Tier 1 Conditions") + "  (universal — all resource types)")
    print(f"    {'Condition':<38}  {'Type':<8}  Description")
    print(f"    {'─'*38}  {'─'*8}  {'─'*35}")
    print(
        f"    {'min_estimated_monthly_cost_usd':<38}  {'float':<8}  "
        "Min cost (USD/mo) to trigger"
    )
    print(f"    {'ai_priority':<38}  {'list':<8}  [high] / [medium] / [low]")
    print(f"    {'idle_days_min':<38}  {'int':<8}  Days since last activity")
    print()

    # Tier 2 — metric-based conditions
    metrics = getattr(spec, "metrics", None) or []
    if metrics:
        print(_bold("  ▸ Tier 2 Conditions") + "  (metric-based — this type only)")
        print(f"    {'Condition (metric name)':<38}  {'Type':<8}  Operators")
        print(f"    {'─'*38}  {'─'*8}  {'─'*35}")
        for m in metrics:
            name = m if isinstance(m, str) else getattr(m, "name", str(m))
            print(f"    {name:<38}  {'float':<8}  lt / gt / lte / gte / eq")
        print()
    else:
        print(_warn("  ▸ Tier 2 Conditions") + "  none — Tier 1 only for this type")
        print()

    # Valid actions
    actions = getattr(spec, "actions", None) or []
    action_str = (
        "  ".join(_ok(f"[{a}]") for a in actions) if actions else "(none defined)"
    )
    print(f"  ▸ {_bold('Valid actions:')}  {action_str}")

    if getattr(spec, "docs_url", None):
        print(f"  ▸ Docs: {spec.docs_url}")  # type: ignore[attr-defined]
    print()
