from adapters.base import CloudAdapter, Resource
from core.baseline import run_baseline

VOL = "AWS::EC2::Volume"
EIP = "AWS::EC2::EIP"
INST = "AWS::EC2::Instance"


class StateAdapter(CloudAdapter):
    def __init__(self, states=None, error=None):
        self._states = states or {}
        self._error = error
        self.state_calls = []

    def list_resources(self, ignore_regions=None):
        return []

    def get_metrics(self, resource_id, resource_type, days=90):
        raise AssertionError("state rules must not need metrics")

    def get_cost(self, resource_ids, days=30):
        return {}

    def get_last_activity(self, resource_id, resource_type):
        return None

    def collect_state(self, resources):
        self.state_calls.append([r.resource_id for r in resources])
        if self._error:
            raise self._error
        return {
            k: v
            for k, v in self._states.items()
            if k in {r.resource_id for r in resources}
        }


def _res(rid, rtype, tags=None, name=None):
    return Resource(rid, rtype, "aws", "us-east-1", tags=tags or {}, name=name)


def _volume(state="available", size=100, vtype="gp3", **kw):
    return {
        "kind": "ebs_volume",
        "state": state,
        "size_gb": size,
        "volume_type": vtype,
        "iops": None,
        "throughput": None,
        "attached_to": [],
        "created": "2026-01-02T00:00:00+00:00",
        **kw,
    }


def _run(resources, states, costs=None, error=None):
    adapter = StateAdapter(states, error)
    return run_baseline(adapter, resources, costs or {}, window_days=14), adapter


def test_unattached_volume_is_flagged_with_its_list_price():
    vol = _res("vol-1", VOL, tags={"team": "data"}, name="scratch")

    result, _ = _run([vol], {"vol-1": _volume()})

    (f,) = result.findings
    assert f.detected_by == "rule:ebs-volume-unattached"
    assert f.estimated_monthly_cost == 8.0 and f.cost_basis == "list_price"
    assert f.confidence == "high" and f.priority == "medium"
    assert "100 GiB gp3" in f.waste_reason and "unattached" in f.waste_reason
    assert "snapshot" in f.recommendation.lower()
    assert f.tags == {"team": "data"} and f.name == "scratch"
    assert f.metrics_summary["state"]["state"] == "available"


def test_attached_volume_is_evaluated_but_not_flagged():
    vol = _res("vol-1", VOL)

    result, _ = _run([vol], {"vol-1": _volume(state="in-use", attached_to=["i-1"])})

    assert result.findings == [] and result.evaluated_ids == {"vol-1"}


def test_missing_state_is_unknown_not_waste():
    result, _ = _run([_res("vol-1", VOL)], {})

    assert result.findings == [] and result.evaluated_ids == set()


def test_unassociated_elastic_ip():
    eip = _res("eipalloc-1", EIP)
    assoc = _res("eipalloc-2", EIP)
    states = {
        "eipalloc-1": {"kind": "elastic_ip", "associated": False, "target": None},
        "eipalloc-2": {"kind": "elastic_ip", "associated": True, "target": "i-1"},
    }

    result, _ = _run([eip, assoc], states)

    assert [f.resource_id for f in result.findings] == ["eipalloc-1"]
    f = result.findings[0]
    assert f.detected_by == "rule:elastic-ip-unassociated"
    assert f.estimated_monthly_cost == 3.65 and f.priority == "low"
    assert result.evaluated_ids == {"eipalloc-1", "eipalloc-2"}


def test_stopped_instance_costs_its_attached_volumes():
    inst = _res("i-1", INST)
    state = {
        "kind": "ec2_instance",
        "state": "stopped",
        "instance_type": "m5.large",
        "volumes": [
            {"id": "vol-a", "size_gb": 100, "volume_type": "gp3"},
            {"id": "vol-b", "size_gb": 50, "volume_type": "gp2"},
        ],
    }

    result, _ = _run([inst], {"i-1": state})

    (f,) = result.findings
    assert f.detected_by == "rule:ec2-instance-stopped"
    assert f.estimated_monthly_cost == 13.0  # 8.00 + 5.00
    assert f.confidence == "medium"
    assert "stopped" in f.waste_reason and "m5.large" in f.waste_reason


def test_running_instance_and_cost_free_stopped_instance_are_not_flagged():
    running = _res("i-1", INST)
    empty = _res("i-2", INST)
    states = {
        "i-1": {"kind": "ec2_instance", "state": "running", "volumes": []},
        "i-2": {"kind": "ec2_instance", "state": "stopped", "volumes": []},
    }

    result, _ = _run([running, empty], states)

    assert result.findings == []


def test_billed_cost_replaces_the_list_price():
    result, _ = _run([_res("vol-1", VOL)], {"vol-1": _volume()}, costs={"vol-1": 9.75})

    f = result.findings[0]
    assert f.estimated_monthly_cost == 9.75 and f.cost_basis == "billed"


def test_only_resources_with_state_rules_are_asked_about():
    other = Resource("arn:rds", "AWS::RDS::DBInstance", "aws", "us-east-1")

    result, adapter = _run([_res("vol-1", VOL), other], {"vol-1": _volume()})

    assert adapter.state_calls == [["vol-1"]]


def test_a_failing_state_collection_never_breaks_the_scan():
    result, _ = _run([_res("vol-1", VOL)], {}, error=RuntimeError("boom"))

    assert result.findings == []


def test_states_are_exposed_for_the_models_evidence():
    result, _ = _run([_res("vol-1", VOL)], {"vol-1": _volume(state="in-use")})

    assert result.states["vol-1"]["state"] == "in-use"


def test_adapters_without_state_support_are_fine():
    class NoState(StateAdapter):
        collect_state = CloudAdapter.collect_state

    adapter = NoState()
    result = run_baseline(adapter, [_res("vol-1", VOL)], {}, window_days=14)

    assert result.findings == []
