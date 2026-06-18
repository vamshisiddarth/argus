from __future__ import annotations

import boto3
import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger(__name__)

SESSION_DURATION_SECONDS = 3600  # 1 hour — short-lived, auto-expires


def get_session(
    account: dict | None = None,
    region: str = "us-east-1",
) -> boto3.Session:
    """
    Return an authenticated boto3 Session for the given account config.

    Single-account (account is None or has no role_arn):
        Uses the ambient credential chain — Lambda execution role in production,
        ~/.aws/credentials profile in local dev.

    Multi-account (account has role_arn):
        Assumes the specified IAM role via STS. Credentials are temporary
        (1 hour), scoped to read-only permissions in the target account,
        and never stored anywhere.
    """
    if not account or not account.get("role_arn"):
        logger.debug("auth_single_account", region=region)
        return boto3.Session(region_name=region)

    role_arn = account["role_arn"]
    account_name = account.get("name", account.get("id", "unknown"))

    logger.info("auth_assuming_role", account=account_name, role_arn=role_arn)

    try:
        sts = boto3.client("sts", region_name=region)
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"ArgusScan-{account_name}",
            DurationSeconds=SESSION_DURATION_SECONDS,
        )
    except ClientError as exc:
        raise PermissionError(
            f"Failed to assume role {role_arn} for account '{account_name}'. "
            f"Check that the spoke IAM role exists and trusts this account. "
            f"AWS error: {exc}"
        ) from exc

    creds = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )
