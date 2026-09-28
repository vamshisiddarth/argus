#!/usr/bin/env python3
"""
Package smoke test: prove the built wheel works the way users install it.

Installs the wheel into a fresh virtualenv (outside the source tree, so nothing
leaks in from the checkout) and checks that:

  1. `argus --version` reports the expected version
  2. every module in every shipped package imports
  3. `argus policies validate` runs against the bundled policies
  4. a full `argus scan` handler run completes (cloud scan stubbed out,
     DRY_RUN=true, so no credentials or AI spend are needed)

Used by CI on every PR and by the release-candidate workflow. The live-testing
repo runs it too, against the exact wheel attached to the pre-release.

    python scripts/package_smoke.py dist/argus_cloud_optimizer-X.Y.Z-py3-none-any.whl
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

IMPORT_ALL = """
import importlib, pkgutil, sys
failed = []
count = 0
for top in sys.argv[1:]:
    pkg = importlib.import_module(top)
    for mod in pkgutil.walk_packages(pkg.__path__, prefix=top + "."):
        count += 1
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{mod.name}: {type(exc).__name__}: {exc}")
print(f"imported {count} modules from {len(sys.argv) - 1} packages")
if failed:
    print("FAILED:\\n  " + "\\n  ".join(failed))
    sys.exit(1)
"""

STUBBED_SCAN = """
import os, tempfile
from unittest.mock import patch
os.environ.update(
    DRY_RUN="true",
    SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T000/B000/XXXX",
    AI_PROVIDER="anthropic",
    ANTHROPIC_API_KEY="sk-ant-smoke-test",
    LOCAL_REPORT_DIR=tempfile.mkdtemp(),
)
import entrypoints.aws_lambda as al
with patch.object(al, "_build_ai_provider", return_value=object()), patch.object(
    al, "_run_single_account",
    return_value=([], "No idle resources.", ["123456789012"], {}),
), patch.object(al, "_load_previous_report", return_value=None):
    result = al.handler({}, None)
assert result.get("statusCode") == 200, result
print("stubbed scan:", result)
"""


def _wheel_packages(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as zf:
        return sorted(
            {
                name.split("/")[0]
                for name in zf.namelist()
                if name.count("/") == 1 and name.endswith("/__init__.py")
            }
        )


def _run(step: str, cmd: list[str], cwd: Path) -> str:
    print(f"\n▶ {step}")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    print(out[-2000:] if out else "(no output)")
    if proc.returncode != 0:
        print(f"✗ {step} failed (exit {proc.returncode})")
        sys.exit(1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("wheel", type=Path)
    parser.add_argument(
        "--expect-version",
        help="Version `argus --version` must report (default: from wheel filename)",
    )
    args = parser.parse_args()

    wheel = args.wheel.resolve()
    expected = args.expect_version or wheel.name.split("-")[1]
    packages = _wheel_packages(wheel)
    print(f"Wheel: {wheel.name}\nPackages: {', '.join(packages)}")

    with tempfile.TemporaryDirectory(prefix="argus-smoke-") as tmp:
        work = Path(tmp)
        venv.create(work / "venv", with_pip=True)
        bindir = work / "venv" / ("Scripts" if sys.platform == "win32" else "bin")
        py, argus = str(bindir / "python"), str(bindir / "argus")

        _run(
            "Install wheel into a clean venv",
            [py, "-m", "pip", "install", "-q", str(wheel)],
            work,
        )

        out = _run("argus --version", [argus, "--version"], work)
        if out.strip() != f"argus {expected}":
            print(f"✗ expected 'argus {expected}', got '{out.strip()}'")
            sys.exit(1)

        _run("Import every shipped module", [py, "-c", IMPORT_ALL, *packages], work)

        policies = REPO / "config" / "policies"
        _run(
            "argus policies validate (bundled policies)",
            [argus, "policies", "validate", "--dir", str(policies)],
            work,
        )

        _run("Stubbed `argus scan` handler run", [py, "-c", STUBBED_SCAN], work)

    print(f"\n✓ Package smoke test passed for {wheel.name}")


if __name__ == "__main__":
    main()
