"""
Shared remediation runner for all entrypoints.

Called after a scan completes. Loads policies, evaluates findings, creates
Jira tickets. Returns ticket URLs for inclusion in the Slack message.
Never raises — all errors are logged so scan delivery is never blocked.

Log events (key=value, one summary line per run):
  remediation_skipped        debug, reason=<why nothing ran>
  remediation_would_track    dry-run only, one per proposal
  remediation_ticket_failed  one per proposal the tracker rejected (error_type)
  remediation_aborted        whole run failed (error_type); traceback if not
                             a TrackerError
  remediation_summary        findings, proposals, tracked, failed, dry_run
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from integrations.base import TrackerError

if TYPE_CHECKING:
    from core.models.finding import ResourceFinding

logger = logging.getLogger(__name__)


def _is_dry_run() -> bool:
    from core.config import get_settings

    return bool(get_settings().report.dry_run)


def run_remediation(
    findings: list[ResourceFinding], report_url: str | None = None
) -> list[str]:
    """
    Evaluate findings against policies and create Jira tickets for matches.

    Returns ticket URLs (empty if Jira is not configured, no policies found,
    no findings matched, or DRY_RUN is set). Env-vars checked:
      ARGUS_POLICY_DIR  — directory containing *.yaml policy files
                          (default: ./config/policies)
      DRY_RUN           — "true" evaluates policies and logs what would be
                          tracked, but makes no Jira calls
      JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN  — Jira credentials
      ARGUS_INTEGRATIONS_CONFIG  — integrations.yaml path
    """
    policy_dir = os.environ.get("ARGUS_POLICY_DIR", "./config/policies")
    if not Path(policy_dir).is_dir():
        logger.debug(
            "remediation_skipped reason=policy_dir_not_found path=%s", policy_dir
        )
        return []

    try:
        from core.remediation.engine import evaluate
        from core.remediation.loader import load_policies

        policies = load_policies(policy_dir)
        if not policies:
            logger.debug("remediation_skipped reason=no_policies_loaded")
            return []

        proposals = evaluate(findings, policies)
        if not proposals:
            logger.info(
                "remediation_summary findings=%d proposals=0 tracked=0 failed=0 "
                "dry_run=%s",
                len(findings),
                _is_dry_run(),
            )
            return []

        if _is_dry_run():
            for proposal in proposals:
                logger.info(
                    "remediation_would_track resource_id=%s policy_id=%s "
                    "action=%s cost_usd=%.2f",
                    proposal.finding.resource_id,
                    proposal.policy.policy_id,
                    proposal.policy.action,
                    proposal.estimated_monthly_cost_usd,
                )
            logger.info(
                "remediation_summary findings=%d proposals=%d tracked=0 failed=0 "
                "dry_run=True",
                len(findings),
                len(proposals),
            )
            return []

        from integrations.jira.tracker import JiraTracker

        tracker = JiraTracker.from_env(report_url=report_url)
        urls: list[str] = []
        failed = 0
        for proposal in proposals:
            try:
                urls.append(tracker.create(proposal))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning(
                    "remediation_ticket_failed resource_id=%s policy_id=%s "
                    "error_type=%s error=%s",
                    proposal.finding.resource_id,
                    proposal.policy.policy_id,
                    type(exc).__name__,
                    exc,
                )
        logger.info(
            "remediation_summary findings=%d proposals=%d tracked=%d failed=%d "
            "dry_run=False",
            len(findings),
            len(proposals),
            len(urls),
            failed,
        )
        return urls
    except TrackerError as exc:
        # Expected operational failure: missing Jira env/config, auth, network.
        logger.warning(
            "remediation_aborted error_type=%s error=%s", type(exc).__name__, exc
        )
        return []
    except Exception as exc:  # noqa: BLE001 — must never block scan delivery
        # Anything else (bad policy file, bug) gets a traceback so it can be
        # told apart from a Jira outage.
        logger.warning(
            "remediation_aborted error_type=%s error=%s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return []
