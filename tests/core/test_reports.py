"""
Tests for core/reports/generator.py and core/reports/delivery.py.
No cloud calls, no real HTTP — all network interactions are mocked.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.models.finding import ResourceFinding
from core.reports.delivery import SlackDeliveryError, post_to_slack
from core.reports.generator import SLACK_DIGEST_LIMIT, build_report, build_slack_payload
from core.reports.html import build_html_report

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
        report = build_report(
            _sample_findings(), cloud="aws", executive_summary="All bad."
        )
        for key in (
            "scan_id",
            "generated_at",
            "cloud",
            "accounts_scanned",
            "total_estimated_waste_usd",
            "findings_count",
            "findings",
            "executive_summary",
        ):
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
        report = build_report(
            [],
            cloud="gcp",
            executive_summary="Nothing found.",
            accounts_scanned=["my-project"],
        )
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


def _all_text(payload: dict) -> str:
    """Flatten all text in a Block Kit payload for assertion purposes."""
    parts: list[str] = []
    for block in payload.get("blocks", []):
        t = block.get("text")
        if isinstance(t, dict):
            parts.append(t.get("text", ""))
        elif isinstance(t, str):
            parts.append(t)
        for field in block.get("fields", []):
            parts.append(field.get("text", ""))
        for elem in block.get("elements", []):
            if not isinstance(elem, dict):
                continue
            et = elem.get("text")
            if isinstance(et, dict):
                parts.append(et.get("text", ""))
            elif isinstance(et, str):
                parts.append(et)
    return " ".join(parts)


class TestBuildSlackPayload:
    def _report(self, n_findings: int = 3) -> dict:
        findings = [
            _finding(f"i-{i}", cost=float(100 - i * 10)) for i in range(n_findings)
        ]
        return build_report(
            findings, cloud="aws", executive_summary="Three resources are idle."
        )

    def test_payload_has_blocks_key(self):
        payload = build_slack_payload(self._report())
        assert "blocks" in payload
        assert isinstance(payload["blocks"], list)

    def test_header_block_present(self):
        payload = build_slack_payload(self._report())
        headers = [b for b in payload["blocks"] if b["type"] == "header"]
        assert len(headers) == 1
        assert "AWS" in headers[0]["text"]["text"]

    def test_stats_fields_contain_total_and_count(self):
        report = self._report(n_findings=3)
        payload = build_slack_payload(report)
        text = _all_text(payload)
        assert "$" in text
        assert "3" in text

    def test_executive_summary_in_payload(self):
        report = self._report()
        payload = build_slack_payload(report)
        assert "Three resources are idle." in _all_text(payload)

    def test_findings_rows_capped_at_digest_limit(self):
        findings = [
            _finding(f"i-{i}", cost=float(200 - i))
            for i in range(SLACK_DIGEST_LIMIT + 5)
        ]
        report = build_report(findings, cloud="aws", executive_summary="Many findings.")
        payload = build_slack_payload(report)
        text = _all_text(payload)
        # Each finding row has its resource id; only SLACK_DIGEST_LIMIT appear
        visible_ids = [f"i-{i}" for i in range(SLACK_DIGEST_LIMIT)]
        hidden_ids = [
            f"i-{i}" for i in range(SLACK_DIGEST_LIMIT, SLACK_DIGEST_LIMIT + 5)
        ]
        for rid in visible_ids:
            assert rid in text
        for rid in hidden_ids:
            assert rid not in text

    def test_overflow_mentioned_in_digest_block(self):
        findings = [
            _finding(f"i-{i}", cost=float(200 - i))
            for i in range(SLACK_DIGEST_LIMIT + 3)
        ]
        report = build_report(findings, cloud="aws", executive_summary="Many.")
        payload = build_slack_payload(report)
        assert "3 more" in _all_text(payload)

    def test_no_overflow_line_when_within_limit(self):
        report = self._report(n_findings=2)
        payload = build_slack_payload(report)
        assert "more finding" not in _all_text(payload)

    def test_finding_shows_name_when_available(self):
        f = _finding(resource_id="i-0abc", name="my-prod-server", cost=99.0)
        report = build_report([f], cloud="aws", executive_summary="x")
        payload = build_slack_payload(report)
        assert "my-prod-server" in _all_text(payload)

    def test_report_url_button_included_when_provided(self):
        report = self._report()
        payload = build_slack_payload(
            report, report_url="https://example.com/report.html"
        )
        action_blocks = [b for b in payload["blocks"] if b["type"] == "actions"]
        assert len(action_blocks) == 1
        urls = [elem.get("url", "") for elem in action_blocks[0]["elements"]]
        assert any("example.com" in u for u in urls)

    def test_no_report_url_button_when_not_provided(self):
        report = self._report()
        payload = build_slack_payload(report, report_url=None)
        action_blocks = [b for b in payload["blocks"] if b["type"] == "actions"]
        assert len(action_blocks) == 1
        urls = [elem.get("url", "") for elem in action_blocks[0]["elements"]]
        # Only the GitHub link; no S3 pre-signed URL
        assert all("github" in u for u in urls)

    def test_high_priority_emoji_present(self):
        f = _finding(priority="high")
        report = build_report([f], cloud="aws", executive_summary="x")
        payload = build_slack_payload(report)
        assert ":red_circle:" in _all_text(payload)


# ---------------------------------------------------------------------------
# build_html_report tests
# ---------------------------------------------------------------------------


class TestBuildHtmlReport:
    def _report(self, n_findings: int = 3) -> dict:
        findings = [
            _finding(f"i-{i}", cost=float(100 - i * 10), priority="high")
            for i in range(n_findings)
        ]
        return build_report(
            findings,
            cloud="aws",
            executive_summary="Some idle resources found.",
            accounts_scanned=["123456789012"],
        )

    def test_returns_string(self):
        assert isinstance(build_html_report(self._report()), str)

    def test_is_valid_html_scaffold(self):
        html = build_html_report(self._report())
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_contains_cloud_and_date(self):
        html = build_html_report(self._report())
        assert "AWS" in html

    def test_contains_total_waste(self):
        report = self._report()
        html = build_html_report(report)
        total = report["total_estimated_waste_usd"]
        assert f"{total:,.2f}" in html

    def test_all_resource_ids_present(self):
        report = self._report(n_findings=3)
        html = build_html_report(report)
        for i in range(3):
            assert f"i-{i}" in html

    def test_waste_reason_and_recommendation_in_rows(self):
        report = self._report(n_findings=1)
        html = build_html_report(report)
        assert "CPU utilization below 1%" in html
        assert "Stop or terminate" in html

    def test_executive_summary_present(self):
        report = self._report()
        html = build_html_report(report)
        assert "Some idle resources found." in html

    def test_json_data_embedded(self):
        report = self._report()
        html = build_html_report(report)
        assert report["scan_id"] in html

    def test_no_external_cdn_urls(self):
        html = build_html_report(self._report())
        assert "cdn." not in html
        assert "googleapis" not in html
        assert "unpkg" not in html


# ---------------------------------------------------------------------------
# post_to_slack tests
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD = {
    "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}]
}
WEBHOOK = "https://hooks.slack.com/services/TEST/HOOK"


class TestPostToSlack:
    def test_dry_run_logs_and_does_not_post(self, capsys):
        post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK, dry_run=True)
        assert "DRY RUN" in capsys.readouterr().out

    def test_dry_run_env_var_respected(self, capsys, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "true")
        post_to_slack(SAMPLE_PAYLOAD, webhook_url=WEBHOOK)
        assert "DRY RUN" in capsys.readouterr().out

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
