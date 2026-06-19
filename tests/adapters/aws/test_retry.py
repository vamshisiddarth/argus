from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from adapters.aws.retry import retry_on_transient


def _make_client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "test"}},
        "TestOperation",
    )


class TestRetryOnTransient:
    @patch("adapters.aws.retry.time.sleep")
    def test_retries_on_throttling_then_succeeds(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=[_make_client_error("ThrottlingException"), "ok"])
        result = retry_on_transient(fn, "arg1", key="val")
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once()

    @patch("adapters.aws.retry.time.sleep")
    def test_retries_on_request_limit_exceeded(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=[_make_client_error("RequestLimitExceeded"), "ok"])
        result = retry_on_transient(fn)
        assert result == "ok"

    @patch("adapters.aws.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep: MagicMock):
        fn = MagicMock(side_effect=_make_client_error("ThrottlingException"))
        with pytest.raises(ClientError):
            retry_on_transient(fn)
        assert fn.call_count == 3

    def test_raises_immediately_on_non_retryable(self):
        fn = MagicMock(side_effect=_make_client_error("AccessDeniedException"))
        with pytest.raises(ClientError):
            retry_on_transient(fn)
        assert fn.call_count == 1

    def test_succeeds_without_retry(self):
        fn = MagicMock(return_value="ok")
        assert retry_on_transient(fn, "a", b="c") == "ok"
        fn.assert_called_once_with("a", b="c")
