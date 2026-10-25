"""
Current state of resources whose waste has no metric signal.

An unattached EBS volume or an unassociated Elastic IP never shows up in
CloudWatch; the only way to know is to ask EC2 what it looks like right now.
These are read-only Describe calls, one set per region. A denied or failed call
leaves the resource without state, which means no rule can fire for it: unknown
is never reported as wasteful.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError

from adapters.aws.config import BOTO_TIMEOUT_CONFIG
from adapters.base import Resource

logger = structlog.get_logger(__name__)

VOLUME = "AWS::EC2::Volume"
EIP = "AWS::EC2::EIP"
INSTANCE = "AWS::EC2::Instance"
STATE_TYPES = frozenset({VOLUME, EIP, INSTANCE})


def collect_state(
    session: boto3.Session, resources: list[Resource]
) -> dict[str, dict[str, Any]]:
    """{resource_id: state} for the volumes, Elastic IPs and instances given."""
    wanted: dict[str, dict[str, list[Resource]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in resources:
        if r.resource_type in STATE_TYPES:
            wanted[r.region][r.resource_type].append(r)

    out: dict[str, dict[str, Any]] = {}
    for region, by_type in sorted(wanted.items()):
        client = session.client("ec2", region_name=region, config=BOTO_TIMEOUT_CONFIG)
        volumes = (
            _volumes(client, region)
            if (VOLUME in by_type or INSTANCE in by_type)
            else {}
        )
        for r in by_type.get(VOLUME, []):
            state = volumes.get(_last(r.resource_id))
            if state is not None:
                out[r.resource_id] = state
        if EIP in by_type:
            addresses = _addresses(client, region)
            for r in by_type[EIP]:
                state = addresses.get(_last(r.resource_id))
                if state is not None:
                    out[r.resource_id] = state
        if INSTANCE in by_type:
            instances = _instances(client, region, volumes)
            for r in by_type[INSTANCE]:
                state = instances.get(_last(r.resource_id))
                if state is not None:
                    out[r.resource_id] = state
    return out


def _last(resource_id: str) -> str:
    return resource_id.rsplit("/", 1)[-1]


def _warn(what: str, region: str, exc: Exception) -> None:
    code = (
        exc.response.get("Error", {}).get("Code", "")
        if isinstance(exc, ClientError)
        else type(exc).__name__
    )
    logger.warning("state_collection_failed", what=what, region=region, error=code)


def _volumes(client: Any, region: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        for page in client.get_paginator("describe_volumes").paginate():
            for v in page.get("Volumes", []):
                created = v.get("CreateTime")
                out[v["VolumeId"]] = {
                    "kind": "ebs_volume",
                    "state": v.get("State"),
                    "size_gb": v.get("Size"),
                    "volume_type": v.get("VolumeType", "gp2"),
                    "iops": v.get("Iops"),
                    "throughput": v.get("Throughput"),
                    "attached_to": [
                        a["InstanceId"]
                        for a in v.get("Attachments", [])
                        if "InstanceId" in a
                    ],
                    "created": created.isoformat() if created else None,
                }
    except (ClientError, BotoCoreError) as exc:
        _warn("describe_volumes", region, exc)
        return {}
    return out


def _addresses(client: Any, region: str) -> dict[str, dict[str, Any]]:
    try:
        addresses = client.describe_addresses().get("Addresses", [])
    except (ClientError, BotoCoreError) as exc:
        _warn("describe_addresses", region, exc)
        return {}
    return {
        a["AllocationId"]: {
            "kind": "elastic_ip",
            "associated": "AssociationId" in a,
            "target": a.get("InstanceId") or a.get("NetworkInterfaceId"),
            "public_ip": a.get("PublicIp"),
        }
        for a in addresses
        if "AllocationId" in a
    }


def _instances(
    client: Any, region: str, volumes: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        for page in client.get_paginator("describe_instances").paginate():
            for reservation in page.get("Reservations", []):
                for i in reservation.get("Instances", []):
                    launched = i.get("LaunchTime")
                    attached = [
                        vid
                        for m in i.get("BlockDeviceMappings", [])
                        if (vid := m.get("Ebs", {}).get("VolumeId"))
                    ]
                    out[i["InstanceId"]] = {
                        "kind": "ec2_instance",
                        "state": i.get("State", {}).get("Name"),
                        "instance_type": i.get("InstanceType"),
                        "launched": launched.isoformat() if launched else None,
                        "volumes": [
                            {
                                "id": vid,
                                "size_gb": volumes[vid]["size_gb"],
                                "volume_type": volumes[vid]["volume_type"],
                            }
                            for vid in attached
                            if vid in volumes
                        ],
                    }
    except (ClientError, BotoCoreError) as exc:
        _warn("describe_instances", region, exc)
        return {}
    return out
