from datetime import datetime, timezone
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from adapters.aws.state import collect_state
from adapters.base import Resource

VOL = "AWS::EC2::Volume"
EIP = "AWS::EC2::EIP"
INST = "AWS::EC2::Instance"


def _res(kind, rid, rtype, region="us-east-1"):
    return Resource(
        f"arn:aws:ec2:{region}:1:{kind}/{rid}", rtype, "aws", region, native_type=None
    )


def _client(volumes=None, addresses=None, instances=None, errors=None):
    errors = errors or {}
    client = MagicMock()

    def paginator(name):
        pag = MagicMock()
        if name == "describe_volumes":
            data = [{"Volumes": volumes or []}]
        elif name == "describe_instances":
            data = [{"Reservations": [{"Instances": instances or []}]}]
        else:
            raise AssertionError(name)
        if name in errors:
            pag.paginate.side_effect = errors[name]
        else:
            pag.paginate.return_value = data
        return pag

    client.get_paginator.side_effect = paginator
    if "describe_addresses" in errors:
        client.describe_addresses.side_effect = errors["describe_addresses"]
    else:
        client.describe_addresses.return_value = {"Addresses": addresses or []}
    return client


def _session(by_region):
    session = MagicMock()
    session.client.side_effect = lambda name, region_name=None, **kw: by_region[
        region_name
    ]
    return session


def _denied(op):
    return ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": "x"}}, op)


def test_volume_state_size_type_and_attachment():
    client = _client(
        volumes=[
            {
                "VolumeId": "vol-1",
                "State": "available",
                "Size": 100,
                "VolumeType": "gp3",
                "Iops": 3000,
                "Throughput": 125,
                "Attachments": [],
                "CreateTime": datetime(2026, 1, 2, tzinfo=timezone.utc),
            },
            {
                "VolumeId": "vol-2",
                "State": "in-use",
                "Size": 50,
                "VolumeType": "gp2",
                "Attachments": [{"InstanceId": "i-9", "State": "attached"}],
            },
        ]
    )
    res = [_res("volume", "vol-1", VOL), _res("volume", "vol-2", VOL)]

    state = collect_state(_session({"us-east-1": client}), res)

    v1 = state[res[0].resource_id]
    assert v1["kind"] == "ebs_volume" and v1["state"] == "available"
    assert (v1["size_gb"], v1["volume_type"], v1["iops"]) == (100, "gp3", 3000)
    assert v1["attached_to"] == [] and v1["created"].startswith("2026-01-02")
    assert state[res[1].resource_id]["attached_to"] == ["i-9"]


def test_only_volumes_in_the_inventory_are_returned():
    client = _client(volumes=[{"VolumeId": "vol-x", "State": "available", "Size": 1}])
    res = [_res("volume", "vol-1", VOL)]

    assert collect_state(_session({"us-east-1": client}), res) == {}


def test_elastic_ip_association():
    client = _client(
        addresses=[
            {"AllocationId": "eipalloc-1", "PublicIp": "1.2.3.4"},
            {
                "AllocationId": "eipalloc-2",
                "PublicIp": "5.6.7.8",
                "AssociationId": "eipassoc-1",
                "InstanceId": "i-1",
            },
        ]
    )
    res = [_res("elastic-ip", "eipalloc-1", EIP), _res("elastic-ip", "eipalloc-2", EIP)]

    state = collect_state(_session({"us-east-1": client}), res)

    assert state[res[0].resource_id]["associated"] is False
    assert state[res[1].resource_id]["associated"] is True
    assert state[res[1].resource_id]["target"] == "i-1"


def test_stopped_instance_state_with_attached_volumes():
    client = _client(
        volumes=[
            {"VolumeId": "vol-1", "State": "in-use", "Size": 100, "VolumeType": "gp3"}
        ],
        instances=[
            {
                "InstanceId": "i-1",
                "State": {"Name": "stopped"},
                "InstanceType": "m5.large",
                "LaunchTime": datetime(2026, 3, 1, tzinfo=timezone.utc),
                "BlockDeviceMappings": [{"Ebs": {"VolumeId": "vol-1"}}],
            }
        ],
    )
    res = [_res("instance", "i-1", INST)]

    state = collect_state(_session({"us-east-1": client}), res)[res[0].resource_id]

    assert state["kind"] == "ec2_instance" and state["state"] == "stopped"
    assert state["instance_type"] == "m5.large"
    assert state["volumes"] == [{"id": "vol-1", "size_gb": 100, "volume_type": "gp3"}]


def test_regions_are_queried_separately():
    east = _client(volumes=[{"VolumeId": "vol-e", "State": "available", "Size": 1}])
    west = _client(volumes=[{"VolumeId": "vol-w", "State": "in-use", "Size": 2}])
    res = [
        _res("volume", "vol-e", VOL, "us-east-1"),
        _res("volume", "vol-w", VOL, "eu-west-1"),
    ]

    state = collect_state(_session({"us-east-1": east, "eu-west-1": west}), res)

    assert state[res[0].resource_id]["state"] == "available"
    assert state[res[1].resource_id]["state"] == "in-use"


def test_a_denied_call_skips_that_resource_type_without_inventing_state():
    client = _client(
        errors={"describe_volumes": _denied("DescribeVolumes")},
        addresses=[{"AllocationId": "eipalloc-1"}],
    )
    res = [_res("volume", "vol-1", VOL), _res("elastic-ip", "eipalloc-1", EIP)]

    state = collect_state(_session({"us-east-1": client}), res)

    assert res[0].resource_id not in state  # unknown, so no rule can fire
    assert state[res[1].resource_id]["associated"] is False


def test_other_resource_types_make_no_calls():
    client = _client()
    res = [Resource("arn:x", "AWS::RDS::DBInstance", "aws", "us-east-1")]

    assert collect_state(_session({"us-east-1": client}), res) == {}
    client.get_paginator.assert_not_called()
    client.describe_addresses.assert_not_called()


def _ec_client(groups, clusters, snaps=None, images=None):
    client = MagicMock()

    def paginator(name):
        pag = MagicMock()
        data = {
            "describe_replication_groups": [{"ReplicationGroups": groups}],
            "describe_cache_clusters": [{"CacheClusters": clusters}],
        }[name]
        pag.paginate.return_value = data
        return pag

    client.get_paginator.side_effect = paginator
    client.describe_snapshots.return_value = {"Snapshots": snaps or []}
    client.describe_images.return_value = {"Images": images or []}
    return client


def _multi_session(ec2, elasticache):
    session = MagicMock()
    session.client.side_effect = lambda name, region_name=None, **kw: (
        elasticache if name == "elasticache" else ec2
    )
    return session


def test_cache_node_state_carries_role_and_failover_settings():
    group = {
        "ReplicationGroupId": "shared",
        "AutomaticFailover": "enabled",
        "MultiAZ": "enabled",
        "NodeGroups": [
            {
                "NodeGroupMembers": [
                    {"CacheClusterId": "shared-001", "CurrentRole": "primary"},
                    {"CacheClusterId": "shared-002", "CurrentRole": "replica"},
                ]
            }
        ],
    }
    clusters = [
        {"CacheClusterId": "shared-001", "ReplicationGroupId": "shared"},
        {"CacheClusterId": "shared-002", "ReplicationGroupId": "shared"},
        {"CacheClusterId": "solo"},
    ]
    session = _multi_session(MagicMock(), _ec_client([group], clusters))
    res = [
        Resource(
            f"arn:aws:elasticache:us-east-1:1:cluster:{n}",
            "AWS::ElastiCache::CacheCluster",
            "aws",
            "us-east-1",
        )
        for n in ("shared-002", "solo")
    ]

    out = collect_state(session, res)

    replica = out[res[0].resource_id]
    assert replica["role"] == "replica" and replica["automatic_failover"] == "enabled"
    assert replica["replication_group"] == "shared" and replica["group_size"] == 2
    assert out[res[1].resource_id]["role"] == "standalone"


def test_cache_state_is_missing_when_describe_is_denied():
    ec = MagicMock()
    pag = MagicMock()
    pag.paginate.side_effect = _denied("DescribeReplicationGroups")
    ec.get_paginator.return_value = pag
    session = _multi_session(MagicMock(), ec)
    res = [
        Resource(
            "arn:aws:elasticache:us-east-1:1:cluster:x",
            "AWS::ElastiCache::CacheCluster",
            "aws",
            "us-east-1",
        )
    ]

    assert collect_state(session, res) == {}


def test_snapshot_state_says_whether_an_ami_uses_it():
    ec2 = MagicMock()
    ec2.describe_snapshots.return_value = {
        "Snapshots": [
            {"SnapshotId": "snap-1", "VolumeSize": 500},
            {"SnapshotId": "snap-2", "VolumeSize": 20},
        ]
    }
    ec2.describe_images.return_value = {
        "Images": [
            {
                "ImageId": "ami-9",
                "BlockDeviceMappings": [{"Ebs": {"SnapshotId": "snap-1"}}],
            }
        ]
    }
    session = _multi_session(ec2, MagicMock())
    res = [
        Resource(
            f"arn:aws:ec2:us-east-1::snapshot/{s}", "ec2:snapshot", "aws", "us-east-1"
        )
        for s in ("snap-1", "snap-2")
    ]

    out = collect_state(session, res)

    assert out[res[0].resource_id]["ami_backed"] is True
    assert out[res[0].resource_id]["ami"] == "ami-9"
    assert out[res[1].resource_id]["ami_backed"] is False
    assert out[res[0].resource_id]["size_gb"] == 500


def _rds_client(snapshots=None, clusters=None, error=None):
    rds = MagicMock()

    def paginator(name):
        pag = MagicMock()
        if error:
            pag.paginate.side_effect = error
        elif name == "describe_db_snapshots":
            pag.paginate.return_value = [{"DBSnapshots": snapshots or []}]
        else:
            pag.paginate.return_value = [{"DBClusterSnapshots": clusters or []}]
        return pag

    rds.get_paginator.side_effect = paginator
    return rds


def _rds_session(rds):
    session = MagicMock()
    session.client.side_effect = lambda name, region_name=None, **kw: (
        rds if name == "rds" else MagicMock()
    )
    return session


def _snap(arn, rtype="rds:snapshot"):
    return Resource(arn, rtype, "aws", "us-east-1")


def test_rds_snapshot_state_carries_type_and_source():
    auto = "arn:aws:rds:us-east-1:1:snapshot:rds:qa-ephemeral-2026-11-01-03-05"
    manual = "arn:aws:rds:us-east-1:1:snapshot:old-manual"
    rds = _rds_client(
        snapshots=[
            {
                "DBSnapshotArn": auto,
                "SnapshotType": "automated",
                "DBInstanceIdentifier": "qa-ephemeral",
                "AllocatedStorage": 20,
                "Status": "available",
                "SnapshotCreateTime": datetime(2026, 11, 1, tzinfo=timezone.utc),
            },
            {"DBSnapshotArn": manual, "SnapshotType": "manual"},
        ]
    )

    out = collect_state(_rds_session(rds), [_snap(auto), _snap(manual)])

    assert out[auto]["snapshot_type"] == "automated"
    assert out[auto]["source"] == "qa-ephemeral" and out[auto]["size_gb"] == 20
    assert out[manual]["snapshot_type"] == "manual"


def test_rds_cluster_snapshot_state():
    arn = "arn:aws:rds:us-east-1:1:cluster-snapshot:rds:prod-2026-11-01"
    rds = _rds_client(
        clusters=[
            {
                "DBClusterSnapshotArn": arn,
                "SnapshotType": "automated",
                "DBClusterIdentifier": "prod",
            }
        ]
    )

    out = collect_state(_rds_session(rds), [_snap(arn, "rds:cluster-snapshot")])

    assert out[arn]["snapshot_type"] == "automated" and out[arn]["source"] == "prod"


def test_rds_snapshot_state_is_missing_when_describe_is_denied():
    rds = _rds_client(error=_denied("DescribeDBSnapshots"))
    arn = "arn:aws:rds:us-east-1:1:snapshot:rds:x"

    assert collect_state(_rds_session(rds), [_snap(arn)]) == {}
