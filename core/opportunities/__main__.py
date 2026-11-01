"""python -m core.opportunities summary --report R [--list N]

Measure how many opportunities a report's findings collapse into. Titles are
printed only with --list, so a quick run never prints resource names.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.opportunities.grouping import (
    DEFAULT_MAX_OPPORTUNITIES,
    DEFAULT_MIN_GROUP_SIZE,
    build_opportunity_block,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.opportunities")
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summary", help="group a report's findings and measure")
    summary.add_argument("--report", required=True, type=Path)
    summary.add_argument("--min-group-size", type=int, default=DEFAULT_MIN_GROUP_SIZE)
    summary.add_argument(
        "--max-opportunities", type=int, default=DEFAULT_MAX_OPPORTUNITIES
    )
    summary.add_argument("--list", type=int, default=0, metavar="N", dest="list_n")
    args = parser.parse_args(argv)

    findings = json.loads(args.report.read_text(encoding="utf-8")).get("findings") or []
    opps, stats = build_opportunity_block(
        findings, args.min_group_size, args.max_opportunities
    )
    ratio = stats["reduction_ratio"]
    print(f"findings: {stats['findings']}")
    print(f"opportunities: {stats['opportunities']}")
    print(f"reduction: {ratio}x" if ratio else "reduction: n/a")
    print(f"easy: {stats['lanes']['easy']}  doubt: {stats['lanes']['doubt']}")
    print(f"largest opportunity (members): {stats['largest_members']}")
    print(f"other bucket (members): {stats['other_bucket_members']}")
    print(f"min group size used: {stats['min_group_size']}")
    total = sum(o["savings"]["high_usd"] for o in opps)
    low = sum(o["savings"]["low_usd"] for o in opps)
    print(f"dollars: low ${low:,.2f}, high ${total:,.2f}")
    for o in opps[: args.list_n]:
        s = o["savings"]
        print(
            f"- [{o['lane']}] {o['title']} "
            f"(${s['low_usd']:,.2f} to ${s['high_usd']:,.2f}, {o['id']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
