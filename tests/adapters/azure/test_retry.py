from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import HttpResponseError

from adapters.azure.retry import retry_on_transient


def _make_http_error(status: int) -> HttpResponseError:
    error = HttpResponseError(message="test")
    error.status_code = status
    return error


class TestRetryOnTransient:
    @patch("adapters.azure.retry.time.sleep")
    def test_retries_on_429(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=[_make_http_error(429), "ok"])
        result = retry_on_transient(fn)
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once()

    @patch("adapters.azure.retry.time.sleep")
    def test_retries_on_503(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=[_make_http_error(503), "ok"])
        result = retry_on_transient(fn)
        assert result == "ok"

    @patch("adapters.azure.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=_make_http_error(429))
        with pytest.raises(HttpResponseError):
            retry_on_transient(fn)
        assert fn.call_count == 3

    def test_raises_immediately_on_non_retryable(self):
        fn = MagicMock(side_effect=_make_http_error(403))
        with pytest.raises(HttpResponseError):
            retry_on_transient(fn)
        assert fn.call_count == 1

    @patch("adapters.azure.retry.time.sleep")
    def test_respects_retry_after_header(self, mock_sleep: MagicMock):
        error = _make_http_error(429)
        mock_response = MagicMock()
        mock_response.headers = {"Retry-After": "2.5"}
        error.response = mock_response
        fn = MagicMock(side_effect=[error, "ok"])
        retry_on_transient(fn)
        mock_sleep.assert_called_once_with(2.5)

    def test_succeeds_without_retry(self):
        fn = MagicMock(return_value="ok")
        assert retry_on_transient(fn, "a", b="c") == "ok"
        fn.assert_called_once_with("a", b="c")
