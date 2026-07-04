"""
JiraTracker — orchestrates dedup, diff, create, and comment.

Flow per proposal:
  1. Build deterministic dedup label: argus:<resource_id>:<policy_id>
  2. Query Jira for open issues with that label in the configured project
  3a. Open ticket found + analysis unchanged → silent skip, return existing URL
  3b. Open ticket found + analysis changed → add comment, return existing URL
  3c. Ticket exists but Done/Closed → create new (resource regressed)
  3d. No ticket → create
"""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

from core.remediation.models import ChangeProposal
from integrations.base import ChangeTracker, TrackerError
from integrations.jira.client import JiraClient
from integrations.jira.formatter import (
    build_issue_fields,
    build_update_comment,
    extract_snapshot,
    fingerprint,
)

logger = logging.getLogger(__name__)

_DONE_STATUSES = frozenset({"done", "closed", "resolved", "won't do", "wont do"})


class JiraTracker(ChangeTracker):
    def __init__(
        self,
        client: JiraClient,
        *,
        project: str,
        issue_type: str = "Task",
        default_labels: list[str] | None = None,
        priority_map: dict[str, str] | None = None,
        report_url: str | None = None,
    ) -> None:
        self._client = client
        self._project = project
        self._issue_type = issue_type
        self._default_labels = default_labels or ["argus", "cost-optimization"]
        self._priority_map = priority_map or {
            "high": "High",
            "medium": "Medium",
            "low": "Low",
        }
        self._report_url = report_url

    # ------------------------------------------------------------------
    # ChangeTracker interface
    # ------------------------------------------------------------------

    def create(self, proposal: ChangeProposal) -> str:
        label = _dedup_label(proposal)
        jql = (
            f'project = "{self._project}" '
            f'AND labels = "{label}" '
            f'AND statusCategory != Done'
        )

        try:
            existing = self._client.search(jql, max_results=1)
        except Exception as exc:
            raise TrackerError(f"Jira search failed: {exc}") from exc

        if existing:
            issue = existing[0]
            key = issue["key"]
            url = self._client.issue_url(key)
            self._maybe_update(issue, proposal)
            _audit(proposal, key, url)
            return url

        url = self._create_new(proposal, label)
        key = url.rsplit("/", 1)[-1]
        _audit(proposal, key, url)
        return url

    def close(self, url: str, reason: str) -> None:
        # Transition to Done not implemented in v1 — log only
        logger.info("tracker_close_requested url=%s reason=%s", url, reason)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_update(
        self, issue: dict[str, Any], proposal: ChangeProposal
    ) -> None:
        key = issue["key"]
        description_text = _extract_description_text(issue)
        stored = extract_snapshot(description_text)
        current = fingerprint(proposal)

        if stored is None or stored != current:
            comment = build_update_comment(proposal, stored or {})
            try:
                self._client.add_comment(key, comment)
                logger.info(
                    "ticket_updated key=%s resource_id=%s",
                    key,
                    proposal.finding.resource_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ticket_comment_failed key=%s error=%s", key, exc)
        else:
            logger.info(
                "ticket_unchanged_skipped key=%s resource_id=%s",
                key,
                proposal.finding.resource_id,
            )

    def _create_new(self, proposal: ChangeProposal, label: str) -> str:
        fields = build_issue_fields(
            proposal,
            project=self._project,
            issue_type=self._issue_type,
            default_labels=self._default_labels,
            priority_map=self._priority_map,
            dedup_label=label,
            report_url=self._report_url,
        )
        try:
            result = self._client.create_issue(fields)
        except Exception as exc:
            raise TrackerError(
                f"Jira create_issue failed for {proposal.finding.resource_id}: {exc}"
            ) from exc

        key = result.get("key", "UNKNOWN")
        url = self._client.issue_url(key)
        logger.info(
            "ticket_created key=%s resource_id=%s policy_id=%s url=%s",
            key,
            proposal.finding.resource_id,
            proposal.policy.policy_id,
            url,
        )
        return url

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, report_url: str | None = None) -> "JiraTracker":
        """
        Build a JiraTracker from environment variables + optional integrations.yaml.

        Required env vars:
          JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN

        Optional config file (ARGUS_INTEGRATIONS_CONFIG,
        default ./config/integrations.yaml):
          Provides project, issue_type, default_labels, priority_map.
        """
        base_url = os.environ.get("JIRA_BASE_URL", "").strip()
        email = os.environ.get("JIRA_USER_EMAIL", "").strip()
        token = os.environ.get("JIRA_API_TOKEN", "").strip()

        missing = [
            name
            for name, val in [
                ("JIRA_BASE_URL", base_url),
                ("JIRA_USER_EMAIL", email),
                ("JIRA_API_TOKEN", token),
            ]
            if not val
        ]
        if missing:
            raise TrackerError(
                f"Missing required env vars: {', '.join(missing)}. "
                "Set them to enable Jira ticket creation."
            )

        client = JiraClient(base_url, email, token)
        config = _load_integrations_config()
        jira_cfg = config.get("jira", {})

        project = jira_cfg.get("project", "")
        if not project:
            raise TrackerError(
                "integrations.yaml missing 'jira.project'. "
                "Set it to the Jira project key (e.g. INFRA)."
            )

        return cls(
            client,
            project=project,
            issue_type=jira_cfg.get("issue_type", "Task"),
            default_labels=jira_cfg.get(
                "default_labels", ["argus", "cost-optimization"]
            ),
            priority_map=jira_cfg.get("priority_map", {}),
            report_url=report_url,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _dedup_label(proposal: ChangeProposal) -> str:
    """Deterministic label: argus:<resource_id>:<policy_id>."""
    rid = proposal.finding.resource_id.replace('"', "").replace(" ", "_")
    pid = proposal.policy.policy_id.replace('"', "").replace(" ", "_")
    return f"argus:{rid}:{pid}"


def _audit(proposal: ChangeProposal, jira_key: str, jira_url: str) -> None:
    try:
        from core.remediation.audit import log_proposal
        log_proposal(proposal, jira_key=jira_key, jira_url=jira_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit_failed proposal_id=%s error=%s", proposal.proposal_id, exc)


def _extract_description_text(issue: dict[str, Any]) -> str:
    """Pull plain text from an issue's description field (ADF or raw string)."""
    desc = issue.get("fields", {}).get("description") or ""
    if isinstance(desc, str):
        return desc
    # ADF: walk content nodes and collect text values
    parts: list[str] = []
    _walk_adf(desc, parts)
    return "\n".join(parts)


def _walk_adf(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text":
            out.append(node.get("text", ""))
        for child in node.get("content", []):
            _walk_adf(child, out)


def _load_integrations_config() -> dict:
    config_path = os.environ.get(
        "ARGUS_INTEGRATIONS_CONFIG", "./config/integrations.yaml"
    )
    try:
        with open(config_path) as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        logger.warning(
            "integrations_config_not_found path=%s "
            "ticket_creation_will_use_defaults",
            config_path,
        )
        return {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("integrations_config_load_failed error=%s", exc)
        return {}
