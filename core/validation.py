"""
Startup environment validation.

Called once at the top of each entrypoint before any cloud API calls are made.
Raises ConfigurationError with a clear, actionable message if required env vars
are missing or malformed. This prevents wasting a 15-minute scan that would
fail at the very end due to a missing credential.

No cloud SDK imports here — this is core/ and must stay cloud-free.
"""

from __future__ import annotations

import json
import os
import urllib.parse


class ConfigurationError(Exception):
    """Raised when the environment is misconfigured at startup."""


def validate_environment(cloud: str) -> None:
    """
    Validate all required environment variables for the given cloud.

    Args:
        cloud: "aws" | "gcp" | "azure"

    Raises:
        ConfigurationError: with a human-readable message describing every
            problem found (not just the first one).
    """
    errors: list[str] = []

    _check_ai_provider(errors)
    _check_slack(errors)

    if cloud == "aws":
        _check_aws(errors)
    elif cloud == "gcp":
        _check_gcp(errors)
    elif cloud == "azure":
        _check_azure(errors)

    if errors:
        bullet_list = "\n".join(f"  • {e}" for e in errors)
        raise ConfigurationError(
            f"Argus cannot start — {len(errors)} configuration error(s) found:\n"
            f"{bullet_list}\n\n"
            "Fix the above and re-deploy or re-run."
        )


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------


def _check_ai_provider(errors: list[str]) -> None:
    provider = os.environ.get("AI_PROVIDER", "").strip().lower()

    # Each cloud has its own default, so an empty AI_PROVIDER is fine —
    # the entrypoint will pick the cloud-native default.
    if not provider:
        return

    known = {"anthropic", "bedrock", "vertexai", "azure_openai"}
    if provider not in known:
        errors.append(
            f"AI_PROVIDER={provider!r} is not recognised. "
            f"Valid values: {', '.join(sorted(known))}."
        )
        return  # No point checking credentials for an unknown provider.

    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            errors.append(
                "AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set. "
                "Get a key at https://console.anthropic.com/settings/api-keys"
            )
        elif not key.startswith("sk-ant-"):
            errors.append(
                "ANTHROPIC_API_KEY looks malformed "
                "(expected it to start with 'sk-ant-'). "
                "Check the key in the Anthropic console."
            )

    if provider == "azure_openai":
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        if not endpoint:
            errors.append(
                "AI_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT to be set. "
                "Example: https://<resource>.openai.azure.com/"
            )
        elif not _is_https_url(endpoint):
            errors.append(
                f"AZURE_OPENAI_ENDPOINT={endpoint!r} is not a valid HTTPS URL."
            )


def _check_slack(errors: list[str]) -> None:
    dry_run = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
    if dry_run:
        return  # Webhook not needed in dry-run mode.

    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        errors.append(
            "SLACK_WEBHOOK_URL is not set. "
            "Create an incoming webhook at https://api.slack.com/apps "
            "or set DRY_RUN=true to skip Slack delivery."
        )
        return

    if not _is_https_url(url):
        errors.append(
            f"SLACK_WEBHOOK_URL={url!r} is not a valid HTTPS URL. "
            "Expected format: https://hooks.slack.com/services/..."
        )


# ---------------------------------------------------------------------------
# Cloud-specific checks
# ---------------------------------------------------------------------------


def _check_aws(errors: list[str]) -> None:
    accounts_mode = os.environ.get("ACCOUNTS_MODE", "single").lower()

    if accounts_mode not in ("single", "multi"):
        errors.append(
            f"ACCOUNTS_MODE={accounts_mode!r} is not valid. Use 'single' or 'multi'."
        )

    if accounts_mode == "multi":
        raw = os.environ.get("ACCOUNTS_CONFIG", "").strip()
        if not raw:
            errors.append(
                "ACCOUNTS_MODE=multi requires ACCOUNTS_CONFIG to be set. "
                "Set it to a JSON array of account objects: "
                '[{"id":"123456789012","name":"prod","role_arn":"arn:aws:iam::..."}]'
            )
            return

        try:
            accounts = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(
                f"ACCOUNTS_CONFIG is not valid JSON: {exc}. "
                "Expected a JSON array of account objects."
            )
            return

        if not isinstance(accounts, list) or len(accounts) == 0:
            errors.append(
                "ACCOUNTS_CONFIG must be a non-empty JSON array of account objects."
            )
            return

        for i, acct in enumerate(accounts):
            if not isinstance(acct, dict):
                errors.append(
                    f"ACCOUNTS_CONFIG[{i}] is not an object — each account must be "
                    '{"id": "...", "name": "...", "role_arn": "..."}.'
                )
                continue
            missing = [f for f in ("id", "role_arn") if not acct.get(f)]
            if missing:
                name = acct.get("name", f"index {i}")
                errors.append(
                    f"ACCOUNTS_CONFIG account '{name}' is missing required "
                    f"field(s): {', '.join(missing)}."
                )


def _check_gcp(errors: list[str]) -> None:
    project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
    project_ids = os.environ.get("GCP_PROJECT_IDS", "").strip()
    has_accounts_config = os.environ.get("ACCOUNTS_MODE") == "multi" and os.environ.get(
        "ACCOUNTS_CONFIG", ""
    ).strip() not in ("", "[]")
    if not project_id and not project_ids and not has_accounts_config:
        errors.append(
            "GCP_PROJECT_ID is required for GCP scans. "
            "Set it to your GCP project ID (e.g. my-project-123). "
            "For multi-project, set GCP_PROJECT_IDS (comma-separated)."
        )


def _check_azure(errors: list[str]) -> None:
    raw = os.environ.get("AZURE_SUBSCRIPTION_IDS", "").strip()
    has_accounts_config = os.environ.get("ACCOUNTS_MODE") == "multi" and os.environ.get(
        "ACCOUNTS_CONFIG", ""
    ).strip() not in ("", "[]")
    if not raw and not has_accounts_config:
        errors.append(
            "AZURE_SUBSCRIPTION_IDS is required for Azure scans. "
            "Set it to one or more subscription IDs separated by commas."
        )
        return

    if raw:
        subscription_ids = [s.strip() for s in raw.split(",") if s.strip()]
        if not subscription_ids:
            errors.append(
                "AZURE_SUBSCRIPTION_IDS is set but contains no valid IDs. "
                "Expected one or more GUIDs separated by commas."
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_https_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
        return parsed.scheme == "https" and bool(parsed.netloc)
    except ValueError:
        return False
