"""
Secret manager integration — resolve secret references in environment variables.

If an env var's value matches a secret reference pattern, the real value is
fetched from the corresponding cloud secret manager and the env var is updated
in-place before the config layer reads it.

Supported patterns:
    arn:aws:secretsmanager:<region>:<account>:secret:<name>
        → AWS Secrets Manager
    gcp-secret://<project>/<secret-name>[/<version>]
        → GCP Secret Manager
    akv://<vault-name>/<secret-name>
        → Azure Key Vault

Call ``resolve_secrets()`` once at startup, before ``validate_environment()``.
It is safe to call when no secret references exist — it's a no-op.

This module lives in core/ but imports cloud SDKs lazily inside the resolver
functions (only when a matching reference is found). If the required SDK is
not installed, a clear error is raised.
"""

from __future__ import annotations

import os
import re

import structlog

logger = structlog.get_logger(__name__)

_SECRET_VARS = (
    "ANTHROPIC_API_KEY",
    "SLACK_WEBHOOK_URL",
    "TEAMS_WEBHOOK_URL",
    "WEBHOOK_URL",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
)

_AWS_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[\w-]+:\d+:secret:.+"
)
_GCP_PATTERN = re.compile(r"^gcp-secret://([^/]+)/([^/]+)(?:/([^/]+))?$")
_AKV_PATTERN = re.compile(r"^akv://([^/]+)/(.+)$")


def resolve_secrets() -> None:
    """
    Scan secret-eligible env vars for reference patterns and resolve them.

    Updates ``os.environ`` in-place so downstream code (config layer,
    validation, providers) sees the real values transparently.
    """
    for var in _SECRET_VARS:
        value = os.environ.get(var, "")
        if not value:
            continue

        resolved = _try_resolve(var, value)
        if resolved is not None:
            os.environ[var] = resolved
            logger.info("secret_resolved", var=var)


def _try_resolve(var: str, value: str) -> str | None:
    """Return the resolved secret value, or None if the value is not a reference."""
    if _AWS_ARN_PATTERN.match(value):
        return _resolve_aws(var, value)
    match = _GCP_PATTERN.match(value)
    if match:
        project, name, version = match.groups()
        return _resolve_gcp(var, project, name, version or "latest")
    match = _AKV_PATTERN.match(value)
    if match:
        vault, name = match.groups()
        return _resolve_azure(var, vault, name)
    return None


def _resolve_aws(var: str, arn: str) -> str:
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        raise ImportError(
            f"{var} references AWS Secrets Manager ({arn}) but boto3 is not "
            "installed. Install with: pip install boto3"
        ) from None

    region = arn.split(":")[3]
    client = boto3.client("secretsmanager", region_name=region)
    try:
        resp = client.get_secret_value(SecretId=arn)
    except ClientError as exc:
        raise RuntimeError(
            f"Failed to resolve {var} from AWS Secrets Manager: {exc}"
        ) from exc
    return resp["SecretString"]


def _resolve_gcp(var: str, project: str, name: str, version: str) -> str:
    try:
        from google.cloud import secretmanager
    except ImportError:
        raise ImportError(
            f"{var} references GCP Secret Manager "
            f"(gcp-secret://{project}/{name}/{version}) but "
            "google-cloud-secret-manager is not installed. "
            "Install with: pip install google-cloud-secret-manager"
        ) from None

    client = secretmanager.SecretManagerServiceClient()
    resource = f"projects/{project}/secrets/{name}/versions/{version}"
    try:
        resp = client.access_secret_version(request={"name": resource})
    except Exception as exc:
        raise RuntimeError(
            f"Failed to resolve {var} from GCP Secret Manager: {exc}"
        ) from exc
    return resp.payload.data.decode("utf-8")


def _resolve_azure(var: str, vault_name: str, secret_name: str) -> str:
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError:
        raise ImportError(
            f"{var} references Azure Key Vault "
            f"(akv://{vault_name}/{secret_name}) but azure-keyvault-secrets "
            "is not installed. Install with: pip install azure-keyvault-secrets "
            "azure-identity"
        ) from None

    vault_url = f"https://{vault_name}.vault.azure.net"
    client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    try:
        secret = client.get_secret(secret_name)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to resolve {var} from Azure Key Vault: {exc}"
        ) from exc
    return secret.value
