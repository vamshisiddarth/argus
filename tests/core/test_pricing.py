import pytest

from core.pricing.aws import (
    ALB_MONTHLY,
    CLB_MONTHLY,
    EIP_MONTHLY,
    NAT_GATEWAY_MONTHLY,
    ebs_volume_monthly,
)


def test_fixed_price_resources_use_730_hour_months():
    assert NAT_GATEWAY_MONTHLY == 32.85
    assert ALB_MONTHLY == 16.43
    assert CLB_MONTHLY == 18.25
    assert EIP_MONTHLY == 3.65


@pytest.mark.parametrize(
    ("size", "vtype", "iops", "throughput", "expected"),
    [
        (100, "gp3", None, None, 8.00),
        (100, "gp2", None, None, 10.00),
        (500, "st1", None, None, 22.50),
        (1000, "sc1", None, None, 15.00),
        (100, "standard", None, None, 5.00),
        (100, "gp3", 6000, 250, 28.00),  # 8 + 3000*0.005 + 125*0.04
        (100, "gp3", 3000, 125, 8.00),  # baseline performance is free
        (100, "io1", 3000, None, 207.50),  # 12.5 + 3000*0.065
        (100, "io2", 5000, None, 337.50),  # 12.5 + 5000*0.065
    ],
)
def test_ebs_volume_prices(size, vtype, iops, throughput, expected):
    assert ebs_volume_monthly(size, vtype, iops, throughput) == pytest.approx(expected)


def test_unknown_volume_type_is_priced_like_gp3_not_zero():
    assert ebs_volume_monthly(100, "mystery") == pytest.approx(8.0)


def test_missing_size_is_zero_not_a_guess():
    assert ebs_volume_monthly(None, "gp3") == 0.0
    assert ebs_volume_monthly(0, "gp3") == 0.0
