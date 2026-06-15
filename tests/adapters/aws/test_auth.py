from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from adapters.aws.auth import get_session


class TestGetSessionSingleAccount:
    def test_returns_default_session_when_no_account(self):
        session = get_session(account=None, region="us-west-2")
        assert session is not None
        assert session.region_name == "us-west-2"

    def test_returns_default_session_when_no_role_arn(self):
        session = get_session(account={"id": "123", "name": "dev"}, region="eu-west-1")
        assert session.region_name == "eu-west-1"


class TestGetSessionMultiAccount:
    def _mock_assume_role_response(self):
        return {
            "Credentials": {
                "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
                "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "SessionToken": "AQoDYXdzEJr...",
                "Expiration": "2026-06-06T09:00:00Z",
            }
        }

    def test_assumes_role_and_returns_session(self):
        with patch("adapters.aws.auth.boto3.client") as mock_boto_client:
            mock_sts = MagicMock()
            mock_boto_client.return_value = mock_sts
            mock_sts.assume_role.return_value = self._mock_assume_role_response()

            session = get_session(
                account={
                    "id": "999",
                    "name": "prod",
                    "role_arn": "arn:aws:iam::999:role/ArgusRole",
                },
                region="us-east-1",
            )

        mock_sts.assume_role.assert_called_once()
        call_kwargs = mock_sts.assume_role.call_args.kwargs
        assert call_kwargs["RoleArn"] == "arn:aws:iam::999:role/ArgusRole"
        assert "ArgusScan" in call_kwargs["RoleSessionName"]
        assert session is not None

    def test_raises_permission_error_on_access_denied(self):
        with patch("adapters.aws.auth.boto3.client") as mock_boto_client:
            mock_sts = MagicMock()
            mock_boto_client.return_value = mock_sts
            mock_sts.assume_role.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Not authorized"}},
                "AssumeRole",
            )

            with pytest.raises(PermissionError, match="Failed to assume role"):
                get_session(
                    account={"role_arn": "arn:aws:iam::999:role/ArgusRole"},
                    region="us-east-1",
                )
