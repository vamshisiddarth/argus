"""
Tests for core/reports/generator.py and core/reports/delivery.py.
No cloud calls, no real HTTP — all network interactions are mocked.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.models.finding import ResourceFinding
from core.reports.delivery import SlackDeliveryError, post_to_slack
from core.reports.generator import TOP_FINDINGS_LIMIT, build_report, build_slack_payload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCAN_TIME = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


def _finding(
    resource_id: str = "i-0abc123",
    resource_type: str = "AWS::EC2::Instance",
    cost: float = 50.0,
    priority: str = "high",
    name: str | None = None,
) -> ResourceFinding:
    return ResourceFinding(
        resource_id=resource_id,
        resource_type=resource_type,
        cloud="aws",
        region="us-east-1",
        estimated_monthly_cost=cost,
        waste_reason="CPU utilization below 1% for 30 days.",
        recommendation="Stop or terminate the instance.",
        priority=priority,
        metrics_summary={"CPUUtilization": 0.5},
        tags={"Team": "platform"},
        scan_time=SCAN_TIME,
        name=name,
    )


def _sample_findings() -> list[ResourceFinding]:
    return [
        _finding("i-low", cost=10.0, priority="low"),
        _finding("i-high", cost=200.0, priority="high"),
        _finding("i-mid", cost=75.0, priority="medium"),
    ]


# ---------------------------------------------------------------------------
# build_report tests
# ---------------------------------------------------------------------------

class TestBuildReport:
    def test_report_has_required_keys(self):
        report = build_report(_sample_findings(), cloud="aws", executive_summary="All bad.")
        for key in ("scan_id", "generated_at", "cloud", "accounts_scanned",
                    "total_estimated_waste_usd", "findings_count", "findings", "executive_summary"):
            assert key in report

    def test_findings_sorted_by_cost_descending(self):
        report = build_report(_sample_findings(), cloud="aws", executive_summary="x")
        costs = [f["estimated_monthly_cost"] for f in report["findings"]]
        assert costs == sorted(costs, reverse=True)

    def test_total_waste_is_sum_of_all_findings(self):
        findings = _sample_findings()
        report = build_report(findings, cloud="aws", executive_summary="x")
        assert report["total_estimated_waste_usd"] == pytest.approx(285.0)

    def test_findings_count_matches_list_length(self):
        findings = _sample_findings()
        report = build_report(findings, cloud="aws", executive_summary="x")
        assert report["findings_count"] == 3
        assert len(report["findings"]) == 3

    def test_cloud_and_summary_preserved(self):
        report = build_report([], cloud="gcp", executive_summary="Nothing found.", accounts_scanned=["my-project"])
        assert report["cloud"] == "gcp"
        assert report["executive_summary"] == "Nothing found."
        assert report["accounts_scanned"] == ["my-project"]

    def test_empty_findings_produces_valid_report(self):
        report = build_report([], cloud="azure", executive_summary="Clean account.")
        assert report["findings_count"] == 0
        assert report["total_estimated_waste_usd"] == 0.0
        assert report["findings"] == []

    def test_scan_id_is_unique_per_call(self):
        r1 = build_report([], cloud="aws", executive_summary="x")
        r2 = build_report([], cloud="aws", executive_summary="x")
        assert r1["scan_id"] != r2["scan_id"]

    def test_generated_at_is_iso8601(self):
        report = build_report([], cloud="aws", executive_summary="x")
        # Should parse without error
        dt = datetime.fromisoformat(report["generated_at"])
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# build_slack_payload tests
# ---------------------------------------------------------------------------

class TestBuildSlackPayload:
    def _report(self, n_findings: int = 3) -> dict:
        findings = [_finding(f"i-{i}", cost=float(100 - i * 10)) for i in range(n_findings)]
        return build_report(findings, cloud="aws", executive_summary="Three resources are idle.")

    def test_payload_has_blocks_key(self):
        payload = build_slack_payload(self._report())
        assert "blocks" in payload
        assert isinstance(payload["blocks"], list)

    def test_blocks_contain_header_and_summary(self):
        payload = build_slack_payload(self._report())
        block_texts = [
            b.get("text", {}).get("text", "") + b.get("text", {}).get("text", "")
            for b in payload["blocks"]
            if b.get("type") == "section"
        ]
        combined = " ".join(block_texts)
        assert "Argus" in combined
        assert "AWS" in combined

    def test_each_finding_gets_a_block(self):
        report = self._report(n_findings=3)
        payload = build_slack_payload(report)
        section_blocks = [b for b in payload["blocks"] if b["type"] == "section"]
        # header section + summary section + 3 findings = 5
        assert len(section_blocks) == 5

    def test_top_findings_limit_respected(self):
        findings = [_finding(f"i-{i}", cost=float(200 - i)) for i in range(TOP_FINDINGS_LIMIT + 5)]
        report = build_report(findings, cloud="aws", executive_summary="Many findings.")
        payload = build_slack_payload(report)
        _circle_emojis = (":red_circle:", ":large_yellow_circle:", ":large_green_circle:", ":white_circle:")
        finding_sections = [
            b for b in payload["blocks"]
            if b["type"] == "section" and any(
                b.get("text", {}).get("text", "").startswith(e) for e in _circle_emojis
            )
        ]
        assert len(finding_sections) == TOP_FINDINGS_LIMIT

    def test_overflow_context_block_shown(self):
        findings = [_finding(f"i-{i}", cost=float(200 - i)) for i in range(TOP_FINDINGS_LIMIT + 3)]
        report = build_report(findings, cloud="aws", executive_summary="Many.")
        payload = build_slack_payload(report)
        context_texts = " ".join(
            e["text"]
            for b in payload["blocks"] if b["type"] == "context"
            for e in b.get("elements", [])
        )
        assert "3 more" in context_texts

    def test_no_overflow_block_when_within_limit(self):
        report = self._report(n_findings=3)
        payload = build_slack_payload(report)
        context_texts = " ".join(
            e["text"]
            for b in payload["blocks"] if b["type"] == "context"
            for e in b.get("elements", [])
            if "more finding" in e.get("text", "")
        )
        assert context_texts == ""

    def test_finding_shows_name_when_available(self):
        f = _finding(resource_id="i-0abc", name="my-prod-server", cost=99.0)
        report = build_report([f], cloud="aws", executive_summary="x")
        payload = build_slack_payload(report)
        all_text = " ".join(
            b.get("text", {}).get("text", "") for b in payload["blocks"]
        )
        assert "my-prod-server" in all_text

    def test_priority_emoji_in_finding_block(self):
        f = _finding(priority="high")
        report = build_report([f], cloud="aws", executive_summary="x")
        payload = build_slack_payload(report)
        finding_blocks = [
            b for b in payload["blocks"]
            if b["type"] == "section" and ":red_circle:" in b.get("text", {}).get("text", "")
        ]
        assert len(finding_blocks) == 1


# ---------------------------------------------------------------------------
# post_to_slack tests
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD = {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}]}
WEBHOOK = "https://hooks.slack.com/services/TEST/HOOK"


class TestPostToSlack:
    def test_dry_run_logs_and_does_not_post(self, caplog):
        with caplog.at_level(logging.INFO, logger="core.reports.delivery"):
            post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK, dry_run=True)
        assert "DRY RUN" in caplog.text

    def test_dry_run_env_var_respected(self, caplog, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        with caplog.at_level(logging.INFO, logger="core.reports.delivery"):
            post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK)
        assert "DRY RUN" in caplog.text

    def test_missing_webhook_raises_environment_error(self):
        with pytest.raises(EnvironmentError, match="SLACK_WEBHOOK_URL"):
            post_to_slack(SAMPLE_PAYLOAD, webhook_url="", dry_run=False)

    def test_successful_post(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK, dry_run=False)

        mock_open.assert_called_once()
        req = mock_open.call_args.args[0]
        assert req.get_header("Content-type") == "application/json"
        body = json.loads(req.data.decode())
        assert body == SAMPLE_PAYLOAD

    def test_http_error_raises_slack_delivery_error(self):
        import urllib.error
        http_err = urllib.error.HTTPError(WEBHOOK, 400, "Bad Request", {}, None)

        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(SlackDeliveryError, match="HTTP 400"):
                post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK, dry_run=False)

    def test_url_error_raises_slack_delivery_error(self):
        import urllib.error
        url_err = urllib.error.URLError("Connection refused")

        with patch("urllib.request.urlopen", side_effect=url_err):
            with pytest.raises(SlackDeliveryError, match="Failed to reach"):
                post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK, dry_run=False)

    def test_unexpected_slack_response_raises(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"invalid_token"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(SlackDeliveryError, match="Unexpected Slack response"):
                post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK, dry_run=False)
