from datetime import datetime, timezone

import pytest

from core.models.finding import ResourceFinding


SCAN_TIME = datetime(2026, 6, 6, 8, 0, 0, tzinfo=timezone.utc)
LAST_ACTIVITY = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


def make_finding(**overrides) -> ResourceFinding:
    defaults = dict(
        resource_id="i-0abc1234567890",
        resource_type="AWS::EC2::Instance",
        cloud="aws",
        region="us-east-1",
        estimated_monthly_cost=45.60,
        waste_reason="0.8% average CPU over 14 days with no network traffic.",
        recommendation="Stop or terminate the instance. Snapshot the EBS volume first.",
        priority="high",
        metrics_summary={"avg_cpu_pct": 0.8, "network_bytes_out": 0},
        tags={"team": "backend", "env": "staging"},
        scan_time=SCAN_TIME,
    )
    defaults.update(overrides)
    return ResourceFinding(**defaults)


class TestResourceFindingCreation:
    def test_required_fields(self):
        f = make_finding()
        assert f.resource_id == "i-0abc1234567890"
        assert f.cloud == "aws"
        assert f.priority == "high"

    def test_optional_fields_default_to_none(self):
        f = make_finding()
        assert f.name is None
        assert f.last_activity is None

    def test_optional_fields_set(self):
        f = make_finding(name="my-server", last_activity=LAST_ACTIVITY)
        assert f.name == "my-server"
        assert f.last_activity == LAST_ACTIVITY


class TestToDict:
    def test_keys_present(self):
        result = make_finding().to_dict()
        expected_keys = {
            "resource_id", "resource_type", "cloud", "region", "name",
            "estimated_monthly_cost", "waste_reason", "recommendation",
            "priority", "metrics_summary", "tags", "last_activity", "scan_time",
        }
        assert expected_keys == set(result.keys())

    def test_scan_time_is_iso_string(self):
        result = make_finding().to_dict()
        assert result["scan_time"] == "2026-06-06T08:00:00+00:00"

    def test_last_activity_none_when_not_set(self):
        result = make_finding().to_dict()
        assert result["last_activity"] is None

    def test_last_activity_is_iso_string_when_set(self):
        result = make_finding(last_activity=LAST_ACTIVITY).to_dict()
        assert result["last_activity"] == "2026-05-01T12:00:00+00:00"

    def test_cost_preserved(self):
        result = make_finding(estimated_monthly_cost=123.45).to_dict()
        assert result["estimated_monthly_cost"] == 123.45


class TestFromDict:
    def test_round_trip(self):
        original = make_finding(name="web-01", last_activity=LAST_ACTIVITY)
        data = original.to_dict()
        restored = ResourceFinding.from_dict(data, scan_time=SCAN_TIME)

        assert restored.resource_id == original.resource_id
        assert restored.cloud == original.cloud
        assert restored.estimated_monthly_cost == original.estimated_monthly_cost
        assert restored.priority == original.priority
        assert restored.last_activity == original.last_activity
        assert restored.name == original.name

    def test_missing_optional_fields_use_defaults(self):
        data = {
            "resource_id": "vol-0123",
            "resource_type": "AWS::EC2::Volume",
            "cloud": "aws",
            "region": "us-west-2",
            "estimated_monthly_cost": 8.0,
            "waste_reason": "Unattached for 30 days",
            "recommendation": "Delete the volume",
            "priority": "medium",
            "metrics_summary": {},
        }
        f = ResourceFinding.from_dict(data, scan_time=SCAN_TIME)
        assert f.name is None
        assert f.last_activity is None
        assert f.tags == {}
