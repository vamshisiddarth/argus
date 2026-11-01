"""
`argus board`: turn a JSON scan report into the static board page.
No cloud calls and no model calls.
"""

from __future__ import annotations

import json
from pathlib import Path

REPORT = (
    Path(__file__).resolve().parents[2] / "testbed" / "fixtures" / "synthetic-scan.json"
)


def _run(argv: list[str]) -> int:
    from entrypoints.cli import main

    try:
        result = main(argv)
        return result if isinstance(result, int) else 0
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0


def _copy(tmp_path: Path, name: str = "scan.json") -> Path:
    path = tmp_path / name
    path.write_text(REPORT.read_text())
    return path


class TestBoardCommand:
    def test_writes_the_page_next_to_the_report_by_default(self, tmp_path, capsys):
        report = _copy(tmp_path)

        code = _run(["board", "--report", str(report)])

        page = tmp_path / "scan.board.html"
        assert code == 0
        assert page.exists()
        assert page.read_text().startswith("<!doctype html>")
        assert str(page) in capsys.readouterr().out

    def test_out_is_honoured_and_parent_directories_are_created(self, tmp_path):
        report = _copy(tmp_path)
        out = tmp_path / "reports" / "q4" / "board.html"

        code = _run(["board", "--report", str(report), "--out", str(out)])

        assert code == 0 and out.exists()

    def test_works_without_a_cloud_or_credentials(self, tmp_path, monkeypatch):
        for var in (
            "AWS_PROFILE",
            "AWS_ACCESS_KEY_ID",
            "GCP_PROJECT_ID",
            "AZURE_SUBSCRIPTION_IDS",
        ):
            monkeypatch.delenv(var, raising=False)

        assert _run(["board", "--report", str(_copy(tmp_path))]) == 0

    def test_a_missing_report_is_an_error(self, tmp_path, capsys):
        code = _run(["board", "--report", str(tmp_path / "nope.json")])

        assert code == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_a_file_that_is_not_json_is_an_error(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text("this is not json")

        code = _run(["board", "--report", str(bad)])

        assert code == 1
        assert "not a valid json" in capsys.readouterr().err.lower()

    def test_json_without_findings_is_an_error(self, tmp_path, capsys):
        other = tmp_path / "other.json"
        other.write_text(json.dumps({"hello": "world"}))

        code = _run(["board", "--report", str(other)])

        assert code == 1
        assert "scan report" in capsys.readouterr().err.lower()

    def test_never_overwrites_the_report_itself(self, tmp_path, capsys):
        report = _copy(tmp_path)
        before = report.read_text()

        code = _run(["board", "--report", str(report), "--out", str(report)])

        assert code == 1
        assert report.read_text() == before
        assert "same file" in capsys.readouterr().err.lower()

    def test_an_older_report_without_opportunities_still_works(self, tmp_path):
        data = json.loads(REPORT.read_text())
        for key in ("opportunities", "opportunity_summary", "cost_summary"):
            data.pop(key, None)
        old = tmp_path / "old.json"
        old.write_text(json.dumps(data))

        code = _run(["board", "--report", str(old)])

        assert code == 0
        assert "<article" in (tmp_path / "old.board.html").read_text()
