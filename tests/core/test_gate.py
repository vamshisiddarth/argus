import pytest

from adapters.base import Resource
from core.pipeline.evidence import Evidence
from core.pipeline.gate import gate

EC2 = "AWS::EC2::Instance"
RDS = "AWS::RDS::DBInstance"
GIB = 1024**3


def _ev(rtype, metrics, status="ok", rid="x-1"):
    r = Resource(f"arn:aws:x:us-east-1:1:{rid}", rtype, "aws", "us-east-1")
    return Evidence(r, metrics=metrics, metrics_status=status)


def _busy_ec2(**kw):
    m = {"CPUUtilization": 55.0, "NetworkIn": 4 * GIB, "NetworkOut": 4 * GIB}
    m.update(kw)
    return _ev(EC2, m)


def _busy_rds(**kw):
    m = {
        "CPUUtilization": 45.0,
        "DatabaseConnections": 30.0,
        "NetworkReceiveThroughput": 9e9,
    }
    m.update(kw)
    return _ev(RDS, m)


def test_a_clearly_busy_instance_is_settled():
    busy = _busy_ec2()

    residual, settled = gate([busy])

    assert settled == [busy] and residual == []


def test_a_clearly_busy_database_is_settled():
    busy = _busy_rds()

    assert gate([busy]) == ([], [busy])


@pytest.mark.parametrize(
    "overrides",
    [
        {"CPUUtilization": 4.0},
        {"CPUUtilization": 19.9},
        {"NetworkIn": 0.0, "NetworkOut": 1000.0},
        {"CPUUtilization": None},
        {"NetworkIn": None},
    ],
)
def test_an_instance_below_any_threshold_or_missing_a_metric_stays_residual(overrides):
    ev = _busy_ec2(**overrides)

    residual, settled = gate([ev])

    assert residual == [ev] and settled == []


@pytest.mark.parametrize(
    "overrides", [{"CPUUtilization": 3.0}, {"DatabaseConnections": 0.0}]
)
def test_a_quiet_database_stays_residual(overrides):
    ev = _busy_rds(**overrides)

    assert gate([ev]) == ([ev], [])


@pytest.mark.parametrize("status", ["no_data", "error"])
def test_missing_evidence_never_settles(status):
    ev = _ev(
        EC2, {"CPUUtilization": 90.0, "NetworkIn": 9e12, "NetworkOut": 9e12}, status
    )

    assert gate([ev]) == ([ev], [])


def test_other_types_are_never_settled_however_busy():
    ev = _ev("AWS::Lambda::Function", {"Invocations": 1e9, "Duration": 5000.0})

    assert gate([ev]) == ([ev], [])


def test_order_is_preserved_in_both_lists():
    a, b, c, d = (
        _busy_ec2(),
        _ev(EC2, {}, "no_data"),
        _busy_rds(),
        _ev(EC2, {}, "error"),
    )

    residual, settled = gate([a, b, c, d])

    assert residual == [b, d] and settled == [a, c]
