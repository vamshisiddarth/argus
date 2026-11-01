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
CACHE_CLUSTER = "AWS::ElastiCache::CacheCluster"
REPLICATION_GROUP = "AWS::ElastiCache::ReplicationGroup"
SNAPSHOT = "ec2:snapshot"
STATE_TYPES = frozenset({VOLUME, EIP, INSTANCE})
CONTEXT_TYPES = frozenset({CACHE_CLUSTER, REPLICATION_GROUP, SNAPSHOT})


def collect_state(
    session: boto3.Session, resources: list[Resource]
) -> dict[str, dict[str, Any]]:
    """{resource_id: state} for the volumes, Elastic IPs and instances given."""
    wanted: dict[str, dict[str, list[Resource]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in resources:
        if r.resource_type in STATE_TYPES | CONTEXT_TYPES:
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
        if CACHE_CLUSTER in by_type or REPLICATION_GROUP in by_type:
            _cache_state(session, region, by_type, out)
        if SNAPSHOT in by_type:
            snaps = _snapshots(client, region, by_type[SNAPSHOT])
            for r in by_type[SNAPSHOT]:
                state = snaps.get(_last(r.resource_id))
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


def _cache_state(
    session: boto3.Session,
    region: str,
    by_type: dict[str, list[Resource]],
    out: dict[str, dict[str, Any]],
) -> None:
    """Role and failover settings, so a replica is never judged on its own traffic."""
    client = session.client(
        "elasticache", region_name=region, config=BOTO_TIMEOUT_CONFIG
    )
    groups: dict[str, dict[str, Any]] = {}
    roles: dict[str, str] = {}
    try:
        for page in client.get_paginator("describe_replication_groups").paginate():
            for g in page.get("ReplicationGroups", []):
                members = [
                    m
                    for ng in g.get("NodeGroups", [])
                    for m in ng.get("NodeGroupMembers", [])
                ]
                for m in members:
                    roles[m.get("CacheClusterId", "")] = (
                        m.get("CurrentRole") or "unknown"
                    )
                groups[g["ReplicationGroupId"]] = {
                    "kind": "elasticache_replication_group",
                    "automatic_failover": str(g.get("AutomaticFailover", "")).lower(),
                    "multi_az": str(g.get("MultiAZ", "")).lower(),
                    "node_count": len(members),
                }
    except (ClientError, BotoCoreError) as exc:
        _warn("describe_replication_groups", region, exc)
        return
    for r in by_type.get(REPLICATION_GROUP, []):
        group_state = groups.get(_name(r.resource_id))
        if group_state is not None:
            out[r.resource_id] = group_state
    wanted = by_type.get(CACHE_CLUSTER, [])
    if not wanted:
        return
    try:
        clusters = {
            c["CacheClusterId"]: c
            for page in client.get_paginator("describe_cache_clusters").paginate()
            for c in page.get("CacheClusters", [])
        }
    except (ClientError, BotoCoreError) as exc:
        _warn("describe_cache_clusters", region, exc)
        return
    for r in wanted:
        name = _name(r.resource_id)
        cluster = clusters.get(name)
        if cluster is None:
            continue
        rg_id = cluster.get("ReplicationGroupId")
        group = groups.get(rg_id or "")
        if rg_id and group is None:
            continue
        node: dict[str, Any] = {
            "kind": "elasticache_node",
            "replication_group": rg_id,
            "role": roles.get(name, "unknown") if rg_id else "standalone",
        }
        if group:
            node["automatic_failover"] = group["automatic_failover"]
            node["multi_az"] = group["multi_az"]
            node["group_size"] = group["node_count"]
        out[r.resource_id] = node


def _name(resource_id: str) -> str:
    return resource_id.rsplit(":", 1)[-1]


def _snapshots(
    client: Any, region: str, wanted: list[Resource]
) -> dict[str, dict[str, Any]]:
    """Size, age and whether an AMI still uses the snapshot."""
    ids = [_last(r.resource_id) for r in wanted]
    snaps: dict[str, dict[str, Any]] = {}
    try:
        for i in range(0, len(ids), 200):
            resp = client.describe_snapshots(SnapshotIds=ids[i : i + 200])
            for sn in resp.get("Snapshots", []):
                started = sn.get("StartTime")
                snaps[sn["SnapshotId"]] = {
                    "kind": "ebs_snapshot",
                    "size_gb": sn.get("VolumeSize"),
                    "started": started.isoformat() if started else None,
                    "description": (sn.get("Description") or "")[:120],
                    "ami_backed": False,
                }
        images = client.describe_images(Owners=["self"]).get("Images", [])
    except (ClientError, BotoCoreError) as exc:
        _warn("describe_snapshots", region, exc)
        return {}
    for image in images:
        for m in image.get("BlockDeviceMappings", []):
            sid = m.get("Ebs", {}).get("SnapshotId")
            if sid in snaps:
                snaps[sid]["ami_backed"] = True
                snaps[sid]["ami"] = image.get("ImageId")
    return snaps
