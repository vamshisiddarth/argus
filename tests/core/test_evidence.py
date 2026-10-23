import json
from datetime import datetime, timezone

from adapters.base import CloudAdapter, MetricSummary, Resource
from core.pipeline.evidence import Evidence, collect_evidence


class FakeAdapter(CloudAdapter):
    def __init__(self, metrics=None, activity=None):
        self.metrics = metrics or {}
        self.activity = activity or {}
        self.metric_calls = []
        self.activity_calls = []

    def list_resources(self, ignore_regions=None):
        return []

    def get_metrics(self, resource_id, resource_type, days=90):
        self.metric_calls.append((resource_id, days))
        answer = self.metrics.get(resource_id)
        if isinstance(answer, Exception):
            raise answer
        return answer or MetricSummary(resource_id, resource_type, days, {}, False)

    def get_cost(self, resource_ids, days=30):
        return {}

    def get_last_activity(self, resource_id, resource_type):
        self.activity_calls.append(resource_id)
        answer = self.activity.get(resource_id)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _res(rid, rtype="AWS::EC2::Volume", **kw):
    return Resource(rid, rtype, "aws", kw.pop("region", "us-east-1"), **kw)


def _ok(rid, **metrics):
    return MetricSummary(rid, "t", 14, metrics)


def test_every_resource_gets_evidence_in_input_order():
    resources = [_res(f"vol-{i}") for i in (3, 1, 2)]
    adapter = FakeAdapter(
        metrics={r.resource_id: _ok(r.resource_id, ops=0.0) for r in resources}
    )

    ev = collect_evidence(adapter, resources, {}, window_days=14)

    assert [e.resource.resource_id for e in ev] == ["vol-3", "vol-1", "vol-2"]
    assert all(e.metrics_status == "ok" for e in ev)
    assert all(days == 14 for _, days in adapter.metric_calls)


def test_metric_failures_are_recorded_not_raised():
    adapter = FakeAdapter(metrics={"a": RuntimeError("throttled")})

    (e,) = collect_evidence(adapter, [_res("a")], {}, window_days=14)

    assert e.metrics_status == "error"
    assert "throttled" in e.metrics_note


def test_missing_data_stays_missing_and_is_never_zero():
    (e,) = collect_evidence(FakeAdapter(), [_res("a")], {}, window_days=14)

    assert e.metrics_status == "no_data"
    assert e.metrics == {}


def test_activity_is_looked_up_only_when_metrics_could_not_decide():
    resources = [_res("with-data"), _res("no-data")]
    adapter = FakeAdapter(metrics={"with-data": _ok("with-data", ops=5.0)})

    ev = collect_evidence(adapter, resources, {}, window_days=14, activity_days=30)

    assert adapter.activity_calls == ["no-data"]
    by_id = {e.resource.resource_id: e for e in ev}
    assert by_id["with-data"].activity_checked is False
    assert by_id["no-data"].activity_checked is True
    assert by_id["no-data"].last_activity is None


def test_last_activity_is_recorded_when_found():
    when = datetime(2026, 9, 1, tzinfo=timezone.utc)
    adapter = FakeAdapter(activity={"a": when})

    (e,) = collect_evidence(adapter, [_res("a")], {}, window_days=14)

    assert e.last_activity == when


def test_activity_lookups_are_capped_and_can_be_switched_off():
    resources = [_res(f"r{i}") for i in range(5)]
    capped = FakeAdapter()
    collect_evidence(capped, resources, {}, window_days=14, activity_cap=2)
    assert len(capped.activity_calls) == 2

    off = FakeAdapter()
    collect_evidence(off, resources, {}, window_days=14, activity_mode="off")
    assert off.activity_calls == []

    every = FakeAdapter(
        metrics={r.resource_id: _ok(r.resource_id, x=1.0) for r in resources}
    )
    collect_evidence(every, resources, {}, window_days=14, activity_mode="all")
    assert len(every.activity_calls) == 5


def test_activity_errors_do_not_break_evidence():
    adapter = FakeAdapter(activity={"a": RuntimeError("rate limited")})

    (e,) = collect_evidence(adapter, [_res("a")], {}, window_days=14)

    assert e.activity_checked is False


def test_billed_cost_is_attached_only_when_positive():
    resources = [_res("a"), _res("b")]

    ev = collect_evidence(
        FakeAdapter(), resources, {"a": 12.5, "b": 0.0}, window_days=14
    )

    assert ev[0].billed_cost_usd == 12.5
    assert ev[1].billed_cost_usd is None


class TestPromptLine:
    def _ev(self, **kw):
        defaults = dict(
            resource=_res(
                "arn:aws:ec2:us-east-1:1:volume/vol-0abc",
                "AWS::EC2::Volume",
                native_type="ec2:volume",
                tags={"Name": "data", "team": "x" * 100},
                name="data",
            ),
            billed_cost_usd=8.0,
            metrics={"VolumeReadOps": 0.0, "VolumeWriteOps": None, "k": 1.23456},
            metrics_status="ok",
            metrics_note=None,
            last_activity=None,
            activity_checked=False,
        )
        defaults.update(kw)
        return Evidence(**defaults)

    def test_line_is_compact_json_with_index_and_short_id(self):
        line = self._ev().to_prompt(7)

        assert line["i"] == 7
        assert line["id"] == "vol-0abc"
        assert line["t"] == "ec2:volume"
        assert line["r"] == "us-east-1"
        assert line["cost"] == 8.0
        assert line["m"] == {"VolumeReadOps": 0.0, "k": 1.2346}  # None dropped, rounded
        assert "ms" not in line
        assert len(json.dumps(line)) < 400

    def test_tags_are_truncated(self):
        tags = self._ev().to_prompt(0)["tags"]
        assert len(tags["team"]) <= 40

    def test_unavailable_metrics_and_activity_are_explicit(self):
        line = self._ev(
            metrics={},
            metrics_status="no_data",
            activity_checked=True,
            last_activity=None,
        ).to_prompt(0)

        assert line["ms"] == "no_data"
        assert line["la"] == "none_in_window"
        assert "m" not in line

    def test_last_activity_is_a_date(self):
        line = self._ev(
            last_activity=datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
            activity_checked=True,
        ).to_prompt(0)

        assert line["la"] == "2026-09-01"


class TestConfigurationState:
    def test_state_is_attached_and_shown_compactly(self):
        res = _res("vol-1")
        state = {
            "kind": "ebs_volume",
            "state": "in-use",
            "size_gb": 100,
            "volume_type": "gp3",
            "iops": 3000,
            "throughput": None,
            "attached_to": ["i-1"],
            "created": "2026-01-02T00:00:00+00:00",
        }

        (e,) = collect_evidence(
            FakeAdapter(), [res], {}, window_days=14, states={res.resource_id: state}
        )
        line = e.to_prompt(0)

        assert e.state == state
        assert line["st"]["state"] == "in-use"
        assert line["st"]["size_gb"] == 100
        assert "throughput" not in line["st"]  # None dropped
        assert "kind" not in line["st"]

    def test_resources_without_state_have_no_st_key(self):
        (e,) = collect_evidence(FakeAdapter(), [_res("a")], {}, window_days=14)
        assert "st" not in e.to_prompt(0)

    def test_the_prompt_explains_the_st_field(self):
        from core.agent.prompts import build_triage_prompt

        assert "st " in build_triage_prompt("aws", [], [], 14, 30)
        assert "current configuration" in build_triage_prompt("aws", [], [], 14, 30)
