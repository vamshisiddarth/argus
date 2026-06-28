from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from adapters.gcp.cloud_logging import get_last_activity


def _make_log_entry(ts: datetime) -> MagicMock:
    entry = MagicMock()
    entry.timestamp = ts
    return entry


class TestGetLastActivity:
    def test_returns_timestamp_from_most_recent_entry(self):
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        with patch("adapters.gcp.cloud_logging.gcp_logging.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_entries.return_value = [_make_log_entry(ts)]
            result = get_last_activity(
                project_id="my-proj",
                resource_id="//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm",
                resource_type="compute.googleapis.com/Instance",
            )
        assert result == ts

    def test_returns_none_when_no_entries(self):
        with patch("adapters.gcp.cloud_logging.gcp_logging.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_entries.return_value = []
            result = get_last_activity(
                project_id="my-proj",
                resource_id="//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm",
                resource_type="compute.googleapis.com/Instance",
            )
        assert result is None

    def test_list_entries_called_without_timeout_kwarg(self):
        """Regression: list_entries() does not accept timeout= in installed SDK version."""
        with patch("adapters.gcp.cloud_logging.gcp_logging.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_entries.return_value = []
            get_last_activity(
                project_id="my-proj",
                resource_id="//redis.googleapis.com/projects/p/locations/us-central1/instances/r",
                resource_type="redis.googleapis.com/Instance",
            )
        call_kwargs = mock_client.list_entries.call_args.kwargs
        assert "timeout" not in call_kwargs, (
            "list_entries() must not receive timeout= kwarg "
            "(unsupported in google-cloud-logging)"
        )

    def test_returns_none_on_api_error(self):
        from google.api_core.exceptions import GoogleAPICallError

        with patch("adapters.gcp.cloud_logging.gcp_logging.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_entries.side_effect = GoogleAPICallError("boom")
            result = get_last_activity(
                project_id="my-proj",
                resource_id="//compute.googleapis.com/projects/p/zones/us-central1-a/instances/vm",
                resource_type="compute.googleapis.com/Instance",
            )
        assert result is None

    def test_adds_utc_tzinfo_when_missing(self):
        ts_naive = datetime(2026, 1, 10, 8, 0, 0)  # no tzinfo
        with patch("adapters.gcp.cloud_logging.gcp_logging.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.list_entries.return_value = [_make_log_entry(ts_naive)]
            result = get_last_activity(
                project_id="my-proj",
                resource_id="//storage.googleapis.com/projects/p/buckets/b",
                resource_type="storage.googleapis.com/Bucket",
            )
        assert result is not None
        assert result.tzinfo is not None
