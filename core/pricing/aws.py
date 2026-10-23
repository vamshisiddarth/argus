"""
AWS list prices (us-east-1, on-demand) for resources whose cost is a fixed formula.

These are used only where Cost Explorer has no per-resource figure, and findings
priced from them say so (`cost_basis: list_price`). Other regions can differ by
a few percent to tens of percent; the report labels the figure as a list price,
never as billed.
"""

from __future__ import annotations

HOURS_PER_MONTH = 730

NAT_GATEWAY_MONTHLY = round(0.045 * HOURS_PER_MONTH, 2)  # excludes data processing
ALB_MONTHLY = round(0.0225 * HOURS_PER_MONTH, 2)  # excludes LCUs
CLB_MONTHLY = round(0.025 * HOURS_PER_MONTH, 2)
EIP_MONTHLY = round(0.005 * HOURS_PER_MONTH, 2)  # any public IPv4 address

_EBS_GB_MONTH = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}
_EBS_PROVISIONED_IOPS_MONTH = {"io1": 0.065, "io2": 0.065}
_GP3_FREE_IOPS = 3000
_GP3_FREE_THROUGHPUT_MBPS = 125
_GP3_IOPS_MONTH = 0.005
_GP3_THROUGHPUT_MONTH = 0.04


def ebs_volume_monthly(
    size_gb: int | None,
    volume_type: str,
    iops: int | None = None,
    throughput_mbps: int | None = None,
) -> float:
    """Monthly list price of an EBS volume. 0.0 when the size is not known."""
    if not size_gb or size_gb <= 0:
        return 0.0
    vtype = volume_type.lower()
    cost = size_gb * _EBS_GB_MONTH.get(vtype, _EBS_GB_MONTH["gp3"])
    if vtype in _EBS_PROVISIONED_IOPS_MONTH and iops:
        cost += iops * _EBS_PROVISIONED_IOPS_MONTH[vtype]
    if vtype == "gp3":
        if iops and iops > _GP3_FREE_IOPS:
            cost += (iops - _GP3_FREE_IOPS) * _GP3_IOPS_MONTH
        if throughput_mbps and throughput_mbps > _GP3_FREE_THROUGHPUT_MBPS:
            cost += (
                throughput_mbps - _GP3_FREE_THROUGHPUT_MBPS
            ) * _GP3_THROUGHPUT_MONTH
    return round(cost, 2)
