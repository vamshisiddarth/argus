"""
The pipeline reports its stages to the installed progress reporter.
Uses the pipeline engine test helpers; no cloud, no real model.
"""

from __future__ import annotations

from typing import Any

import pytest

from adapters.base import MetricSummary
from core.pipeline.evidence import collect_evidence
from core.progress import Progress, use_progress
from tests.core.test_pipeline_engine import (
    Adapter,
    _f,
    _ok,
    _report,
    _run,
    _vol,
)


class Recorder(Progress):
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def stage(self, key, total=None, unit="items"):
        self.calls.append(("stage", (key, total, unit)))

    def advance(self, n=1, detail=""):
        self.calls.append(("advance", (n, detail)))

    def extend(self, n):
        self.calls.append(("extend", (n,)))

    def note(self, text):
        self.calls.append(("note", (text,)))

    def finish(self, summary=""):
        self.calls.append(("finish", (summary,)))

    def of(self, kind: str) -> list[tuple[Any, ...]]:
        return [args for name, args in self.calls if name == kind]

    def stages(self) -> list[str]:
        return [args[0] for args in self.of("stage")]

    def advances_in(self, key: str) -> int:
        total, active = 0, None
        for name, args in self.calls:
            if name == "stage":
                active = args[0]
            elif name == "advance" and active == key:
                total += args[0]
        return total


@pytest.fixture(autouse=True)
def _pipeline(monkeypatch):
    monkeypatch.setenv("ARGUS_ENGINE", "pipeline")


def _resources(n: int):
    res = [_vol(i) for i in range(n)]
    return res, {r.resource_id: _ok(r.resource_id) for r in res}


class TestEndToEnd:
    def test_stages_run_in_order_and_each_one_is_finished(self):
        rec = Recorder()
        res, metrics = _resources(5)
        adapter = Adapter(res, metrics=metrics)

        with use_progress(rec):
            _run(adapter, [_report(_f(0))])

        assert rec.stages() == ["discover", "rules", "evidence", "model"]
        assert len(rec.of("finish")) == len(rec.of("stage"))

    def test_discovery_says_how_many_resources_were_found(self):
        rec = Recorder()
        res, metrics = _resources(5)

        with use_progress(rec):
            _run(Adapter(res, metrics=metrics), [_report(_f(0))])

        assert "5 resources found" in rec.of("finish")[0][0]

    def test_evidence_advances_once_per_resource(self):
        rec = Recorder()
        res, metrics = _resources(7)

        with use_progress(rec):
            _run(Adapter(res, metrics=metrics), [_report(_f(0))])

        stage = [a for a in rec.of("stage") if a[0] == "evidence"][0]
        assert stage[1] == 7 and stage[2] == "resources"
        assert rec.advances_in("evidence") == 7

    def test_the_model_stage_counts_batches_and_shows_spend(self):
        rec = Recorder()
        res, metrics = _resources(5)

        with use_progress(rec):
            _run(Adapter(res, metrics=metrics), [_report(_f(0))])

        stage = [a for a in rec.of("stage") if a[0] == "model"][0]
        assert stage[2] == "batches" and stage[1] >= 1
        assert rec.advances_in("model") == stage[1]
        details = [a[1] for a in rec.of("advance") if a[1]]
        assert any("of $2.00" in d for d in details)

    def test_the_plan_line_is_announced_before_the_model_runs(self):
        rec = Recorder()
        res, metrics = _resources(5)

        with use_progress(rec):
            _run(Adapter(res, metrics=metrics), [_report(_f(0))])

        notes = [a[0] for a in rec.of("note")]
        assert any(n.startswith("LLM plan:") for n in notes)
        names = [name for name, _ in rec.calls]
        plan_at = next(
            i
            for i, (n, a) in enumerate(rec.calls)
            if n == "note" and a[0].startswith("LLM plan:")
        )
        model_at = next(
            i for i, (n, a) in enumerate(rec.calls) if n == "stage" and a[0] == "model"
        )
        assert plan_at < model_at
        assert names.count("stage") == 4

    def test_no_resources_stops_after_discovery(self):
        rec = Recorder()

        with use_progress(rec):
            _run(Adapter([]), [])

        assert rec.stages() == ["discover"]
        assert "0 resources found" in rec.of("finish")[0][0]

    def test_a_budget_stop_still_brings_the_bar_to_the_end(self, monkeypatch):
        monkeypatch.setenv("LLM_BUDGET_USD", "0.0001")
        rec = Recorder()
        res, metrics = _resources(5)

        with use_progress(rec):
            try:
                _run(Adapter(res, metrics=metrics), [_report(_f(0))])
            except Exception:  # noqa: BLE001
                pass

        model = [a for a in rec.of("stage") if a[0] == "model"]
        if model:
            assert rec.advances_in("model") == model[0][1] + sum(
                a[0] for a in rec.of("extend")
            )

    def test_without_a_reporter_nothing_changes(self):
        res, metrics = _resources(3)

        findings, summary, _, _ = _run(Adapter(res, metrics=metrics), [_report(_f(0))])

        assert len(findings) == 1 and "Analysed" in summary


class TestEvidenceDirectly:
    def test_activity_lookups_extend_the_same_stage(self):
        rec = Recorder()
        res = [_vol(i) for i in range(4)]
        adapter = Adapter(res)

        def no_data(resource_id, resource_type, days=90):
            return MetricSummary(resource_id, resource_type, days, {}, False)

        adapter.get_metrics = no_data

        with use_progress(rec):
            collect_evidence(adapter, res, {}, 14, activity_mode="auto")

        assert rec.of("extend") == [(4,)]
        assert rec.advances_in("evidence") == 8

    def test_a_failing_metrics_call_still_advances(self):
        rec = Recorder()
        res = [_vol(i) for i in range(3)]
        adapter = Adapter(res)

        def boom(resource_id, resource_type, days=90):
            raise RuntimeError("throttled")

        adapter.get_metrics = boom

        with use_progress(rec):
            collect_evidence(adapter, res, {}, 14, activity_mode="off")

        assert rec.advances_in("evidence") == 3
        assert rec.of("finish")

    def test_nothing_is_reported_for_an_empty_list(self):
        rec = Recorder()

        with use_progress(rec):
            assert collect_evidence(Adapter([]), [], {}, 14) == []

        assert rec.calls == []
