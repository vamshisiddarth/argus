"""python -m core.calibration score --report R --manifest M [--baseline B]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.calibration.manifest import filter_manifest, load_manifest
from core.calibration.scoring import compare_to_baseline, render_markdown, score_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.calibration")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="score a scan report against a manifest")
    score.add_argument("--report", required=True, type=Path)
    score.add_argument("--manifest", required=True, type=Path)
    score.add_argument("--baseline", type=Path, help="scorecard JSON to compare with")
    score.add_argument("--tolerance", type=float, default=0.05)
    score.add_argument(
        "--exclude-class",
        action="append",
        default=[],
        help="class not deployed in this run (repeatable)",
    )
    score.add_argument("--json", type=Path, dest="json_out")
    score.add_argument("--md", type=Path, dest="md_out")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    if args.exclude_class:
        manifest = filter_manifest(manifest, set(args.exclude_class))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    card = score_report(report, manifest)
    markdown = render_markdown(card)
    if args.json_out:
        args.json_out.write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    if args.md_out:
        args.md_out.write_text(markdown, encoding="utf-8")
    print(markdown)

    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        problems = compare_to_baseline(card, baseline, args.tolerance)
        for problem in problems:
            print(f"REGRESSION: {problem}", file=sys.stderr)
        if problems:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
