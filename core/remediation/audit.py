from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from core.remediation.models import ChangeProposal

logger = logging.getLogger(__name__)

_DEFAULT_AUDIT_PATH = "./local_reports/audit.jsonl"


def log_proposal(
    proposal: ChangeProposal,
    jira_key: str | None,
    jira_url: str | None,
    *,
    audit_path: str | None = None,
) -> None:
    """
    Append one line to the JSONL audit log.

    Each line records the proposal→Jira mapping so findings can be
    traced back to the scan that generated them.

    File is created on first write. Path defaults to
    ARGUS_AUDIT_LOG env var, then ./local_reports/audit.jsonl.
    """
    path = Path(audit_path or os.environ.get("ARGUS_AUDIT_LOG", _DEFAULT_AUDIT_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "proposal_id": proposal.proposal_id,
        "resource_id": proposal.finding.resource_id,
        "resource_type": proposal.finding.resource_type,
        "cloud": proposal.finding.cloud,
        "region": proposal.finding.region,
        "policy_id": proposal.policy.policy_id,
        "action": proposal.policy.action,
        "estimated_monthly_cost_usd": round(proposal.estimated_monthly_cost_usd, 2),
        "ai_priority": proposal.finding.priority,
        "jira_key": jira_key,
        "jira_url": jira_url,
    }

    try:
        with path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        logger.debug("audit_logged proposal_id=%s jira_key=%s", proposal.proposal_id, jira_key)
    except OSError as exc:
        logger.warning("audit_write_failed path=%s error=%s", path, exc)
