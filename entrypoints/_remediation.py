"""
Shared remediation runner for all entrypoints.

Called after a scan completes. Loads policies, evaluates findings, creates
Jira tickets. Returns ticket URLs for inclusion in the Slack message.
Never raises — all errors are logged so scan delivery is never blocked.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models.finding import ResourceFinding

logger = logging.getLogger(__name__)


def run_remediation(
    findings: list[ResourceFinding], report_url: str | None = None
) -> list[str]:
    """
    Evaluate findings against policies and create Jira tickets for matches.

    Returns ticket URLs (empty if Jira is not configured, no policies found,
    or no findings matched). Env-vars checked:
      ARGUS_POLICY_DIR  — directory containing *.yaml policy files
                          (default: ./config/policies)
      JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN  — Jira credentials
      ARGUS_INTEGRATIONS_CONFIG  — integrations.yaml path
    """
    policy_dir = os.environ.get("ARGUS_POLICY_DIR", "./config/policies")
    if not Path(policy_dir).is_dir():
        logger.debug("remediation_skipped policy_dir_not_found path=%s", policy_dir)
        return []

    try:
        from core.remediation.engine import evaluate
        from core.remediation.loader import load_policies
        from integrations.jira.tracker import JiraTracker

        policies = load_policies(policy_dir)
        if not policies:
            logger.debug("remediation_skipped no_policies_loaded")
            return []

        proposals = evaluate(findings, policies)
        if not proposals:
            logger.debug("remediation_skipped no_proposals_matched")
            return []

        tracker = JiraTracker.from_env(report_url=report_url)
        urls: list[str] = []
        for proposal in proposals:
            try:
                url = tracker.create(proposal)
                urls.append(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "remediation_ticket_failed resource_id=%s error=%s",
                    proposal.finding.resource_id,
                    exc,
                )
        logger.info(
            "remediation_complete tickets=%d proposals=%d", len(urls), len(proposals)
        )
        return urls
    except Exception as exc:  # noqa: BLE001
        logger.warning("remediation_skipped reason=%s", exc)
        return []
