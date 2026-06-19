from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Cloud = Literal["aws", "gcp", "azure"]
Priority = Literal["high", "medium", "low"]
FindingStatus = Literal["new", "recurring", "resolved"]


@dataclass
class ResourceFinding:
    """
    Universal representation of a single idle/wasteful cloud resource.
    Produced by the agent loop, consumed by the report generator.
    No cloud SDK imports — pure Python.
    """

    resource_id: str
    resource_type: str  # e.g. "AWS::EC2::Instance", "AWS::RDS::DBInstance"
    cloud: Cloud  # "aws" | "gcp" | "azure"
    region: str
    estimated_monthly_cost: float  # USD
    waste_reason: str  # AI-written: why this resource is idle/wasteful
    recommendation: str  # AI-written: specific action to take
    priority: Priority  # AI-assigned based on cost + confidence
    metrics_summary: dict[str, Any]  # key signals used to reach this conclusion
    tags: dict[str, str]
    scan_time: datetime
    name: str | None = None
    last_activity: datetime | None = None
    status: FindingStatus = "new"

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "cloud": self.cloud,
            "region": self.region,
            "name": self.name,
            "estimated_monthly_cost": self.estimated_monthly_cost,
            "waste_reason": self.waste_reason,
            "recommendation": self.recommendation,
            "priority": self.priority,
            "metrics_summary": self.metrics_summary,
            "tags": self.tags,
            "last_activity": (
                self.last_activity.isoformat() if self.last_activity else None
            ),
            "scan_time": self.scan_time.isoformat(),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], scan_time: datetime) -> ResourceFinding:
        last_activity = None
        if data.get("last_activity"):
            last_activity = datetime.fromisoformat(data["last_activity"])

        return cls(
            resource_id=data["resource_id"],
            resource_type=data["resource_type"],
            cloud=data["cloud"],
            region=data["region"],
            name=data.get("name"),
            estimated_monthly_cost=float(data["estimated_monthly_cost"]),
            waste_reason=data["waste_reason"],
            recommendation=data["recommendation"],
            priority=data["priority"],
            metrics_summary=data.get("metrics_summary", {}),
            tags=data.get("tags", {}),
            last_activity=last_activity,
            scan_time=scan_time,
            status=data.get("status", "new"),
        )
