"""
Cost, coverage and repeatability on an inventory shaped like a real customer account
(1000 resources over 101 types, taken from a real scan).
"""

import hashlib
import json
from pathlib import Path

import pytest

from adapters.aws.resource_explorer import _is_billable
from adapters.aws.type_map import canonical_type
from adapters.base import CloudAdapter, MetricSummary, Resource
from ai.base import AIProvider, AIResponse, ToolCall
from core.agent.loop import AgentLoop
from core.registry import get_registry

TYPES = json.loads(
    (
        Path(__file__).resolve().parent.parent / "fixtures/real_inventory_types.json"
    ).read_text()
)
ACCOUNTS = [{"id": "123456789012", "name": "prod"}]


def _h(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest(), 16)


def _inventory() -> list[Resource]:
    out = []
    for native, count in TYPES.items():
        service, _, kind = native.partition(":")
        for i in range(count):
            arn = f"arn:aws:{service}:us-east-1:123456789012:{kind}/{kind}-{i:04d}"
            if not _is_billable(native):
                continue
            out.append(
                Resource(
                    arn,
                    canonical_type(native),
                    "aws",
                    "us-east-1",
                    tags={"team": "x"} if i % 3 == 0 else {},
                    native_type=native,
                )
            )
    return out


class RealisticAdapter(CloudAdapter):
    """Deterministic fake cloud: hash-derived metrics, a few unattached volumes."""

    def __init__(self):
        self.inventory = _inventory()

    def list_resources(self, ignore_regions=None):
        return list(self.inventory)

    def get_metrics(self, resource_id, resource_type, days=90):
        if get_registry().get(resource_type) is None:
            return MetricSummary(resource_id, resource_type, days, {}, False)
        idle = _h(resource_id) % 5 == 0
        value = 0.0 if idle else float(_h(resource_id) % 90 + 5)
        return MetricSummary(
            resource_id,
            resource_type,
            days,
            {"CPUUtilization": value, "NetworkOut": value * 100, "Requests": value},
        )

    def get_cost(self, resource_ids, days=30):
        return {}

    def get_last_activity(self, resource_id, resource_type):
        return None

    def collect_state(self, resources):
        return {
            r.resource_id: {
                "kind": "ebs_volume",
                "state": "available" if _h(r.resource_id) % 10 == 0 else "in-use",
                "size_gb": 50,
                "volume_type": "gp3",
                "attached_to": [],
            }
            for r in resources
            if r.resource_type == "AWS::EC2::Volume"
        }


class FlagZeroUsageModel(AIProvider):
    """Stands in for the real model: flags what shows zero usage, bills like it."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools, system_prompt=None):
        self.calls += 1
        text = messages[0].text
        flagged = []
        for line in text.splitlines():
            if line.startswith("{"):
                row = json.loads(line)
                if row.get("m", {}).get("CPUUtilization") == 0.0:
                    flagged.append(
                        {
                            "i": row["i"],
                            "waste_reason": "0% CPU over the window",
                            "recommendation": "stop or delete",
                            "priority": "medium",
                            "confidence": "high",
                            "estimated_monthly_cost": 30.0,
                        }
                    )
        return AIResponse(
            "tool_use",
            None,
            [ToolCall("t", "report_findings", {"findings": flagged})],
            input_tokens=int((len(text) + len(system_prompt or "")) / 3.5),
            output_tokens=60 + 110 * len(flagged),
        )

    def chat_stream(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _pipeline(monkeypatch):
    monkeypatch.setenv("ARGUS_ENGINE", "pipeline")
    monkeypatch.setenv("LLM_BUDGET_USD", "2.0")


def _scan():
    adapter, ai = RealisticAdapter(), FlagZeroUsageModel()
    loop = AgentLoop(ai, adapter)
    findings, summary = loop.run("aws", [], ACCOUNTS)
    return findings, summary, loop, ai, adapter


def test_every_cost_bearing_resource_is_analysed_without_a_cap():
    findings, _, loop, _, adapter = _scan()

    cov = loop.coverage
    assert cov.discovered == len(adapter.inventory) and 150 < cov.discovered < 400
    assert cov.analysed == cov.discovered and cov.dropped == 0
    assert cov.stop_reason is None


def test_a_full_scan_of_a_1000_resource_account_costs_a_fraction_of_the_old_engine():
    _, _, loop, ai, _ = _scan()

    spent = loop.tracker.estimated_cost_usd
    assert spent < 0.60, spent  # the tool-calling engine needed about $0.80 for 200
    assert ai.calls <= 12
    assert loop.scan_window["llm_estimate_usd"] >= spent * 0.5  # estimate is honest


def test_the_estimate_is_not_far_below_what_is_spent():
    _, _, loop, _, _ = _scan()

    assert (
        loop.scan_window["llm_estimate_usd"] >= loop.scan_window["llm_spent_usd"] * 0.6
    )


def test_three_scans_agree_exactly():
    runs = [_scan() for _ in range(3)]

    stories = [
        (
            [
                (f.resource_id, f.detected_by, f.priority, f.estimated_monthly_cost)
                for f in r[0]
            ],
            r[1],
        )
        for r in runs
    ]
    assert stories[0] == stories[1] == stories[2]


def test_unattached_volumes_are_found_by_rule_not_by_the_model():
    findings, _, _, _, _ = _scan()

    rules = [f for f in findings if f.detected_by == "rule:ebs-volume-unattached"]
    assert rules and all(f.cost_basis == "list_price" for f in rules)
    assert all(f.estimated_monthly_cost == 4.0 for f in rules)  # 50 GiB gp3


def test_an_underfunded_budget_stops_cleanly_and_says_how_much_was_covered():
    import os

    os.environ["LLM_BUDGET_USD"] = "0.02"
    from core.config import clear_settings_cache

    clear_settings_cache()
    findings, summary, loop, _, adapter = _scan()

    assert loop.coverage.stop_reason == "budget"
    assert loop.coverage.skipped_by_reason.get("budget", 0) > 0
    assert summary.startswith("Scan aborted: LLM budget")
    assert loop.coverage.analysed < loop.coverage.discovered
    assert any(f.detected_by.startswith("rule:") for f in findings)  # rules survive
