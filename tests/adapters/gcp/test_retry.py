from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable

from adapters.gcp.retry import retry_on_transient


class TestRetryOnTransient:
    @patch("adapters.gcp.retry.time.sleep")
    def test_retries_on_resource_exhausted(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=[ResourceExhausted("quota"), "ok"])
        result = retry_on_transient(fn)
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once()

    @patch("adapters.gcp.retry.time.sleep")
    def test_retries_on_service_unavailable(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=[ServiceUnavailable("down"), "ok"])
        result = retry_on_transient(fn)
        assert result == "ok"

    @patch("adapters.gcp.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=ResourceExhausted("quota"))
        with pytest.raises(ResourceExhausted):
            retry_on_transient(fn)
        assert fn.call_count == 3

    def test_raises_immediately_on_non_retryable(self):
        from google.api_core.exceptions import PermissionDenied

        fn = MagicMock(side_effect=PermissionDenied("nope"))
        with pytest.raises(PermissionDenied):
            retry_on_transient(fn)
        assert fn.call_count == 1

    def test_succeeds_without_retry(self):
        fn = MagicMock(return_value="ok")
        assert retry_on_transient(fn, "a", b="c") == "ok"
        fn.assert_called_once_with("a", b="c")
