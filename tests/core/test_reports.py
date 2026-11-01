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
from core.reports.delivery import (
    SlackDeliveryError,
    SlackNotificationProvider,
    TeamsDeliveryError,
    TeamsNotificationProvider,
    WebhookDeliveryError,
    WebhookNotificationProvider,
    build_notification_providers,
    notify_all,
    post_to_slack,
)
from core.reports.generator import (
    SLACK_DIGEST_LIMIT,
    build_report,
    build_slack_payload,
    synthesize_executive_summary,
    waste_caveat,
)

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
            "schema_version",
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

    def test_schema_version_is_1_2_0(self):
        # 1.1.0: coverage, scan_window, preflight (all optional)
        # 1.2.0: cost_summary (dollars and counts per cost basis)
        report = build_report([], cloud="aws", executive_summary="x")
        assert report["schema_version"] == "1.2.0"

    def test_scan_id_is_unique_per_call(self):
        r1 = build_report([], cloud="aws", executive_summary="x")
        r2 = build_report([], cloud="aws", executive_summary="x")
        assert r1["scan_id"] != r2["scan_id"]

    def test_generated_at_is_iso8601(self):
        report = build_report([], cloud="aws", executive_summary="x")
        # Should parse without error
        dt = datetime.fromisoformat(report["generated_at"])
        assert dt.tzinfo is not None

    def test_registry_warnings_empty_by_default(self):
        report = build_report([], cloud="aws", executive_summary="x")
        assert report["registry_warnings"] == []

    def test_registry_warnings_surfaced_in_report(self):
        warnings = ["aws/AWS::Fake::Type: unknown action 'fly'"]
        report = build_report(
            [], cloud="aws", executive_summary="x", registry_warnings=warnings
        )
        assert report["registry_warnings"] == warnings


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

    def test_scan_errors_block_shown_when_present(self):
        report = build_report(
            [],
            cloud="gcp",
            executive_summary="x",
            accounts_scanned=["proj-ok"],
            scan_errors=[
                {
                    "account_id": "proj-fail",
                    "account_name": "prod",
                    "error": "PermissionError",
                }
            ],
        )
        payload = build_slack_payload(report)
        text = _all_text(payload)
        assert "Partial scan" in text
        assert "prod" in text
        assert "PermissionError" in text

    def test_no_scan_errors_block_when_empty(self):
        report = build_report([], cloud="aws", executive_summary="x", scan_errors=[])
        payload = build_slack_payload(report)
        assert "Partial scan" not in _all_text(payload)

    def test_scan_errors_shows_fraction_succeeded(self):
        report = build_report(
            [],
            cloud="aws",
            executive_summary="x",
            accounts_scanned=["a", "b"],
            scan_errors=[
                {"account_id": "c", "account_name": "c", "error": "denied"},
                {"account_id": "d", "account_name": "d", "error": "denied"},
            ],
        )
        payload = build_slack_payload(report)
        assert "2/4" in _all_text(payload)

    def test_ticket_refs_section_shown_when_provided(self):
        report = self._report()
        urls = [
            "https://jira.example.com/browse/INFRA-1",
            "https://jira.example.com/browse/INFRA-2",
        ]
        payload = build_slack_payload(report, ticket_refs=urls)
        text = _all_text(payload)
        assert "INFRA-1" in text
        assert "INFRA-2" in text
        assert "ticket" in text.lower()

    def test_no_ticket_section_when_refs_empty(self):
        report = self._report()
        payload = build_slack_payload(report, ticket_refs=[])
        text = _all_text(payload)
        assert "ticket" not in text.lower()

    def test_no_ticket_section_when_refs_none(self):
        report = self._report()
        payload = build_slack_payload(report, ticket_refs=None)
        text = _all_text(payload)
        assert "ticket" not in text.lower()

    def test_ticket_count_in_section_header(self):
        report = self._report()
        urls = [f"https://jira.example.com/browse/INFRA-{i}" for i in range(3)]
        payload = build_slack_payload(report, ticket_refs=urls)
        text = _all_text(payload)
        assert "3" in text

    def test_ticket_overflow_truncated_at_10(self):
        report = self._report()
        urls = [f"https://jira.example.com/browse/INFRA-{i}" for i in range(15)]
        payload = build_slack_payload(report, ticket_refs=urls)
        text = _all_text(payload)
        assert "5 more" in text


# ---------------------------------------------------------------------------
# synthesize_executive_summary tests
# ---------------------------------------------------------------------------


def _mock_ai(text: str = "Unified summary text.") -> MagicMock:
    from ai.base import AIResponse

    provider = MagicMock()
    provider.chat.return_value = AIResponse(
        stop_reason="end_turn",
        text=text,
        tool_calls=[],
        input_tokens=100,
        output_tokens=40,
    )
    return provider


class TestSynthesizeExecutiveSummary:
    def _findings(self, n: int = 3) -> list[ResourceFinding]:
        return [_finding(f"r-{i}", cost=float(100 - i * 10)) for i in range(n)]

    def test_returns_ai_text_on_success(self):
        ai = _mock_ai("Great unified summary across 2 projects.")
        text, inp, out = synthesize_executive_summary(
            self._findings(), ["[dev] all good", "[prod] 2 idle"], "gcp", ai
        )
        assert text == "Great unified summary across 2 projects."
        assert inp == 100
        assert out == 40

    def test_calls_ai_with_findings_digest(self):
        ai = _mock_ai()
        synthesize_executive_summary(self._findings(2), ["[dev] summary"], "aws", ai)
        call_args = ai.chat.call_args
        prompt_text = call_args.kwargs["messages"][0].text
        assert "r-0" in prompt_text or "r-1" in prompt_text
        assert "AWS" in prompt_text

    def test_falls_back_to_joined_summaries_on_ai_error(self):
        ai = MagicMock()
        ai.chat.side_effect = RuntimeError("API unavailable")
        text, inp, out = synthesize_executive_summary(
            self._findings(),
            ["[dev] some waste", "[prod] more waste"],
            "aws",
            ai,
        )
        assert "[dev] some waste" in text
        assert "[prod] more waste" in text
        assert inp == 0
        assert out == 0

    def test_no_findings_returns_fallback_without_ai_call(self):
        ai = _mock_ai()
        text, inp, out = synthesize_executive_summary([], [], "azure", ai)
        assert "No idle resources" in text
        assert inp == 0
        ai.chat.assert_not_called()

    def test_empty_ai_response_falls_back(self):
        ai = _mock_ai(text="")
        text, inp, out = synthesize_executive_summary(
            self._findings(), ["[dev] ok"], "gcp", ai
        )
        assert "[dev] ok" in text

    def test_token_counts_returned(self):
        ai = _mock_ai()
        _, inp, out = synthesize_executive_summary(
            self._findings(), ["[dev] ok"], "aws", ai
        )
        assert inp == 100
        assert out == 40


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


class TestTeamsNotificationProvider:
    def test_delivers_to_teams_webhook(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"1"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            provider = TeamsNotificationProvider(
                webhook_url="https://teams.example.com/hook"
            )
            provider.notify(SAMPLE_PAYLOAD)

        mock_open.assert_called_once()
        req = mock_open.call_args.args[0]
        body = json.loads(req.data.decode())
        assert body["@type"] == "MessageCard"
        assert body["title"] == "Argus Cost Optimization Report"

    def test_raises_without_url(self):
        provider = TeamsNotificationProvider(webhook_url="")
        with pytest.raises(EnvironmentError, match="TEAMS_WEBHOOK_URL"):
            provider.notify(SAMPLE_PAYLOAD)

    def test_http_error_raises_teams_delivery_error(self):
        import urllib.error

        http_err = urllib.error.HTTPError(
            "https://teams.example.com", 400, "Bad", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            provider = TeamsNotificationProvider(
                webhook_url="https://teams.example.com/hook"
            )
            with pytest.raises(TeamsDeliveryError, match="HTTP 400"):
                provider.notify(SAMPLE_PAYLOAD)


class TestWebhookNotificationProvider:
    def test_delivers_raw_json(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            provider = WebhookNotificationProvider(
                webhook_url="https://hook.example.com/endpoint"
            )
            provider.notify(SAMPLE_PAYLOAD)

        req = mock_open.call_args.args[0]
        body = json.loads(req.data.decode())
        assert body == SAMPLE_PAYLOAD

    def test_raises_without_url(self):
        provider = WebhookNotificationProvider(webhook_url="")
        with pytest.raises(EnvironmentError, match="WEBHOOK_URL"):
            provider.notify(SAMPLE_PAYLOAD)

    def test_http_error_raises_webhook_delivery_error(self):
        import urllib.error

        http_err = urllib.error.HTTPError(
            "https://hook.example.com", 500, "Error", {}, None
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            provider = WebhookNotificationProvider(
                webhook_url="https://hook.example.com/endpoint"
            )
            with pytest.raises(WebhookDeliveryError, match="HTTP 500"):
                provider.notify(SAMPLE_PAYLOAD)


class TestBuildNotificationProviders:
    def test_default_is_slack(self, monkeypatch):
        monkeypatch.delenv("NOTIFICATION_PROVIDER", raising=False)
        providers = build_notification_providers()
        assert len(providers) == 1
        assert isinstance(providers[0], SlackNotificationProvider)

    def test_comma_separated_multi_provider(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "slack,teams,webhook")
        providers = build_notification_providers()
        assert len(providers) == 3
        assert isinstance(providers[0], SlackNotificationProvider)
        assert isinstance(providers[1], TeamsNotificationProvider)
        assert isinstance(providers[2], WebhookNotificationProvider)

    def test_unknown_provider_skipped(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "slack,email")
        providers = build_notification_providers()
        assert len(providers) == 1
        assert isinstance(providers[0], SlackNotificationProvider)


class TestNotifyAll:
    def test_dry_run_skips_delivery(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "slack")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.example.com/hook")
        with patch("urllib.request.urlopen") as mock_open:
            result = notify_all(SAMPLE_PAYLOAD, dry_run=True)
        mock_open.assert_not_called()
        assert result is True  # dry-run counts as success

    def test_delivers_to_all_providers(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "slack,webhook")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.example.com/hook")
        monkeypatch.setenv("WEBHOOK_URL", "https://hook.example.com/endpoint")

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            result = notify_all(SAMPLE_PAYLOAD, dry_run=False)

        assert mock_open.call_count == 2
        assert result is True

    def test_returns_false_when_all_providers_fail(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "slack")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.example.com/hook")
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = notify_all(SAMPLE_PAYLOAD, dry_run=False)
        assert result is False

    def test_returns_true_when_one_provider_succeeds(self, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_PROVIDER", "slack,webhook")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.example.com/hook")
        monkeypatch.setenv("WEBHOOK_URL", "https://hook.example.com/endpoint")

        mock_resp = MagicMock()
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def urlopen_side_effect(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("first provider failed")
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
            result = notify_all(SAMPLE_PAYLOAD, dry_run=False)

        assert result is True  # second provider succeeded


# ---------------------------------------------------------------------------
# Schema 1.1.0 additions: coverage / scan_window / preflight
# ---------------------------------------------------------------------------

_COVERAGE = {
    "discovered": 880,
    "analysed": 200,
    "dropped": 680,
    "truncated": True,
    "selection": "stratified_by_type",
    "cost_data_available": False,
    "regions_covered": ["us-east-1"],
    "types": {"AWS::EC2::Volume": {"discovered": 880, "analysed": 200}},
}


class TestReportCoverageFields:
    def test_new_keys_present_and_none_by_default(self):
        report = build_report([], cloud="aws", executive_summary="x")
        assert report["coverage"] is None
        assert report["scan_window"] is None
        assert report["preflight"] is None

    def test_new_keys_carry_what_was_passed(self):
        window = {"metrics_lookback_days": 14, "cost_basis": "unavailable"}
        pre = {"skipped": False, "checks": []}
        report = build_report(
            [],
            cloud="aws",
            executive_summary="x",
            coverage=_COVERAGE,
            scan_window=window,
            preflight=pre,
        )
        assert report["coverage"] == _COVERAGE
        assert report["scan_window"] == window
        assert report["preflight"] == pre

    def test_old_report_still_diffs_against_new_report(self):
        from core.reports.comparison import compare_scans

        old = build_report(_sample_findings(), cloud="aws", executive_summary="x")
        old["schema_version"] = "1.0.1"
        for key in ("coverage", "scan_window", "preflight"):
            old.pop(key, None)

        labelled, diff = compare_scans(_sample_findings(), old)

        assert len(labelled) == len(_sample_findings())
        assert all(f.status == "recurring" for f in labelled)


def _rated(rid, cost, confidence, basis="model_estimate"):
    f = _finding(rid, cost=cost)
    f.confidence = confidence
    f.cost_basis = basis
    return f


class TestWasteBreakdown:
    def _findings(self):
        return [
            _rated("a", 100.0, "high"),
            _rated("b", 300.0, "medium"),
            _rated("c", 200.0, "low"),
            _rated("d", 5.0, None),
        ]

    def test_totals_are_split_by_confidence(self):
        report = build_report(self._findings(), cloud="aws", executive_summary="x")

        assert report["waste_by_confidence"] == {
            "high": 100.0,
            "medium": 300.0,
            "low": 200.0,
            "unrated": 5.0,
        }
        assert report["total_estimated_waste_usd"] == 605.0

    def test_total_is_an_estimate_unless_every_finding_is_billed(self):
        estimated = build_report(self._findings(), cloud="aws", executive_summary="x")
        billed = build_report(
            [_rated("a", 10.0, "high", "billed")], cloud="aws", executive_summary="x"
        )
        mixed = build_report(
            [_rated("a", 10.0, "high", "billed"), _rated("b", 5.0, "low")],
            cloud="aws",
            executive_summary="x",
        )

        assert estimated["total_is_estimate"] is True
        assert billed["total_is_estimate"] is False
        assert mixed["total_is_estimate"] is True

    def test_no_findings_is_all_zero_and_not_an_estimate(self):
        report = build_report([], cloud="aws", executive_summary="x")

        assert report["waste_by_confidence"] == {
            "high": 0.0,
            "medium": 0.0,
            "low": 0.0,
            "unrated": 0.0,
        }
        assert report["total_is_estimate"] is False

    def test_slack_headline_says_estimate_and_shows_the_split(self):
        report = build_report(self._findings(), cloud="aws", executive_summary="x")

        text = str(build_slack_payload(report))

        assert "unverified waste estimate" in text
        assert "not billed" in text
        assert "$605.00 model estimate" in text
        assert "$300.00 medium" in text and "$200.00 low" in text

    def test_slack_headline_for_billed_totals_has_no_caveat(self):
        report = build_report(
            [_rated("a", 10.0, "high", "billed")], cloud="aws", executive_summary="x"
        )

        assert "not billed" not in str(build_slack_payload(report))


class TestSpendInReports:
    def _report(self):
        return build_report(
            _sample_findings(),
            cloud="aws",
            executive_summary="x",
            scan_window={
                "metrics_lookback_days": 14,
                "llm_spent_usd": 0.31,
                "llm_estimate_usd": 0.4,
                "llm_budget_usd": 2.0,
            },
        )

    def test_slack_digest_shows_spend(self):
        assert "LLM spend $0.31" in str(build_slack_payload(self._report()))


class TestUntrustedTotals:
    def _named(self, rid, name, cost, basis="model_estimate", confidence="medium"):
        f = _rated(rid, cost, confidence, basis)
        f.name = name
        return f

    def _findings(self):
        return [
            self._named("big", "web-fleet", 3500.0),
            self._named("prod", "PROD - Payments server - DO NOT TOUCH", 40.0),
            self._named("small", "scratch-box", 12.0),
        ]

    def test_prod_like_names_and_high_unbilled_estimates_need_review(self):
        report = build_report(self._findings(), cloud="aws", executive_summary="x")
        by_id = {f["resource_id"]: f for f in report["findings"]}

        assert by_id["big"]["review_required"] is True
        assert by_id["big"]["review_reasons"] == ["high_unbilled_estimate"]
        assert by_id["prod"]["review_required"] is True
        assert by_id["prod"]["review_reasons"] == ["prod_like_name"]
        assert by_id["small"]["review_required"] is False
        assert by_id["small"]["review_reasons"] == []

    def test_high_cost_that_is_billed_is_not_flagged_for_amount(self):
        f = self._named("big", "web-fleet", 3500.0, basis="billed")
        report = build_report([f], cloud="aws", executive_summary="x")

        assert report["findings"][0]["review_required"] is False

    def test_prod_like_name_is_flagged_even_when_billed(self):
        f = self._named("p", "prod-db", 80.0, basis="billed")
        report = build_report([f], cloud="aws", executive_summary="x")

        assert report["findings"][0]["review_reasons"] == ["prod_like_name"]

    def test_names_that_only_contain_prod_as_a_substring_are_not_flagged(self):
        f = self._named("p", "product-images-cache", 80.0)
        report = build_report([f], cloud="aws", executive_summary="x")

        assert report["findings"][0]["review_required"] is False

    def test_report_splits_the_total_into_reviewable_and_needs_review(self):
        report = build_report(self._findings(), cloud="aws", executive_summary="x")

        assert report["findings_needing_review"] == 2
        assert report["waste_needs_review_usd"] == 3540.0
        assert report["total_estimated_waste_usd"] == 3552.0

    def test_billed_clean_report_has_nothing_to_review(self):
        f = self._named("a", "batch-box", 10.0, basis="billed", confidence="high")
        report = build_report([f], cloud="aws", executive_summary="x")

        assert report["findings_needing_review"] == 0
        assert report["waste_needs_review_usd"] == 0.0

    def test_headline_says_estimate_only_unverified_and_the_review_amount(self):
        report = build_report(self._findings(), cloud="aws", executive_summary="x")

        caveat = waste_caveat(report)

        assert "estimate only" in caveat and "unverified" in caveat
        assert "$3,540.00 in 2 findings needs human review" in caveat
