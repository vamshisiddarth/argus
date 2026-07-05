"""
Webhook stub for Jira approval signals — v2 placeholder.

In v2, when a Jira ticket transitions to "Approved", it can fire a webhook
to an executor service. That executor (separate component, write-scoped IAM)
carries out the action. Argus itself stays read-only.

This module logs the incoming signal and does nothing else.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def handle_transition(payload: dict[str, Any]) -> None:
    """
    Called when a Jira issue transition webhook fires.

    v1: log only. v2: route to executor service.
    """
    issue_key = payload.get("issue", {}).get("key", "UNKNOWN")
    status = payload.get("transition", {}).get("to", {}).get("name", "UNKNOWN")
    logger.info(
        "jira_webhook_received issue=%s transition_to=%s "
        "auto_remediation=not_implemented_v2",
        issue_key,
        status,
    )
