"""
The board's pure JavaScript (tally, CSV, import) run under Node. Skipped when
Node is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap

import pytest

from core.reports.board_assets import LOGIC_JS

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not installed"
)


def _run(expression: str) -> object:
    script = textwrap.dedent(
        f"""
        const vm = require('node:vm');
        const ctx = vm.createContext({{}});
        vm.runInContext({json.dumps(LOGIC_JS)}, ctx);
        const out = vm.runInContext({json.dumps(expression)}, ctx);
        process.stdout.write(JSON.stringify(out));
        """
    )
    done = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(done.stdout)


OPPS = (
    "[{id:'a',low:100,high:150,unpriced:0,lane:'easy'},"
    "{id:'b',low:10,high:300,unpriced:2,lane:'doubt'},"
    "{id:'c',low:5,high:5,unpriced:0,lane:'doubt'}]"
)


class TestTally:
    def test_sums_approved_and_investigating_ranges(self):
        t = _run(
            f"BoardLogic.computeTally({OPPS}, "
            "{a:{state:'approve'}, b:{state:'investigate'}})"
        )

        assert t["approved"] == {"low": 100, "high": 150, "count": 1}
        assert t["investigating"] == {"low": 10, "high": 300, "count": 1}
        assert t["undecided"] == 1

    def test_kept_items_are_counted_not_summed(self):
        t = _run(
            f"BoardLogic.computeTally({OPPS}, "
            "{c:{state:'keep', note:'owned by finance'}, a:{state:'keep', note:''}})"
        )

        assert t["kept"] == {"count": 2, "withoutReason": 1}
        assert t["approved"]["count"] == 0

    def test_decisions_for_unknown_opportunities_are_ignored(self):
        t = _run(f"BoardLogic.computeTally({OPPS}, {{zzz:{{state:'approve'}}}})")

        assert t["approved"]["count"] == 0 and t["undecided"] == 3

    def test_share_of_the_total_is_reported(self):
        t = _run(f"BoardLogic.computeTally({OPPS}, {{a:{{state:'approve'}}}})")

        assert t["shareOfHigh"] == pytest.approx(150 / 455)


class TestCsv:
    @pytest.mark.parametrize("cell", ["=1+1", "+SUM(A1)", "-2", "@cmd", "\tx", "\rx"])
    def test_formula_prefixes_are_neutralised(self, cell):
        out = _run(f"BoardLogic.csvCell({json.dumps(cell)})")

        assert out.startswith("'") or out.startswith("\"'")

    def test_commas_quotes_and_newlines_are_quoted(self):
        assert _run("BoardLogic.csvCell('a,b')") == '"a,b"'
        assert _run("BoardLogic.csvCell('say \"hi\"')") == '"say ""hi"""'
        assert _run("BoardLogic.csvCell('a\\nb')") == '"a\nb"'

    def test_plain_values_pass_through(self):
        assert _run("BoardLogic.csvCell('plain')") == "plain"
        assert _run("BoardLogic.csvCell(12.5)") == "12.5"
        assert _run("BoardLogic.csvCell(null)") == ""

    def test_rows_join_with_crlf(self):
        assert _run("BoardLogic.toCsv([['a','b'],['c','d']])") == "a,b\r\nc,d\r\n"


class TestImport:
    def _payload(self, **over):
        base = {
            "schema": "argus-board-decisions/1",
            "scan_id": "s1",
            "decisions": [
                {
                    "opportunity_id": "a",
                    "state": "approve",
                    "note": "ok",
                    "owner": "me",
                    "expires": "",
                    "decided_at": "2026-10-30T10:00:00Z",
                }
            ],
        }
        base.update(over)
        return json.dumps(json.dumps(base))

    def test_accepts_a_valid_export(self):
        r = _run(f"BoardLogic.parseImport({self._payload()})")

        assert r["ok"] is True
        assert r["decisions"]["a"]["state"] == "approve"

    def test_rejects_other_files(self):
        assert _run("BoardLogic.parseImport('not json')")["ok"] is False
        assert _run('BoardLogic.parseImport(\'{"schema":"x"}\')')["ok"] is False

    def test_drops_unknown_states_and_trims_long_text(self):
        long = "x" * 5000
        bad = self._payload(
            decisions=[
                {"opportunity_id": "a", "state": "delete-everything"},
                {"opportunity_id": "b", "state": "keep", "note": long},
            ]
        )

        r = _run(f"BoardLogic.parseImport({bad})")

        assert "a" not in r["decisions"]
        assert len(r["decisions"]["b"]["note"]) <= 1000

    def test_merge_keeps_the_newer_decision(self):
        merged = _run(
            "BoardLogic.mergeDecisions("
            "{a:{state:'approve',decided_at:'2026-10-30T10:00:00Z'}},"
            "{a:{state:'keep',decided_at:'2026-10-30T11:00:00Z'},"
            "b:{state:'approve',decided_at:'2026-10-30T09:00:00Z'}})"
        )

        assert merged["a"]["state"] == "keep"
        assert merged["b"]["state"] == "approve"

    def test_merge_does_not_let_an_older_import_win(self):
        merged = _run(
            "BoardLogic.mergeDecisions("
            "{a:{state:'approve',decided_at:'2026-10-30T12:00:00Z'}},"
            "{a:{state:'keep',decided_at:'2026-10-30T11:00:00Z'}})"
        )

        assert merged["a"]["state"] == "approve"


class TestFilter:
    ROW = "{id:'a',lane:'easy',action:'remove',search:'remove 3 ebs volumes team=x'}"

    @pytest.mark.parametrize(
        "flt,decision,expected",
        [
            ("all", "null", True),
            ("easy", "null", True),
            ("doubt", "null", False),
            ("undecided", "null", True),
            ("undecided", "{state:'approve'}", False),
            ("approve", "{state:'approve'}", True),
            ("keep", "{state:'approve'}", False),
        ],
    )
    def test_chips(self, flt, decision, expected):
        out = _run(
            f"BoardLogic.matches({self.ROW}, {decision}, "
            f"{{chip:'{flt}', action:'all', query:''}})"
        )

        assert out is expected

    def test_search_is_case_insensitive_and_checks_every_word(self):
        def search(text: str) -> object:
            return _run(
                f"BoardLogic.matches({self.ROW}, null, "
                f"{{chip:'all', action:'all', query:{json.dumps(text)}}})"
            )

        assert search("EBS") is True
        assert search("ebs team=x") is True
        assert search("ebs nat") is False

    def test_action_filter(self):
        out = _run(
            f"BoardLogic.matches({self.ROW}, null, "
            "{chip:'all', action:'review', query:''})"
        )

        assert out is False
