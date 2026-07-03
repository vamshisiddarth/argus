from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.models.finding import ResourceFinding
from core.registry import get_registry
from core.remediation.models import (
    ChangeProposal,
    Condition,
    Policy,
    ScopeFilter,
)

logger = logging.getLogger(__name__)


def evaluate(
    findings: list[ResourceFinding],
    policies: list[Policy],
) -> list[ChangeProposal]:
    """
    Match each finding against the policy list (sorted by weight desc).
    First matching policy wins — lower-weight policies are skipped for that finding.
    Returns one ChangeProposal per matched finding.
    """
    if not policies:
        return []

    sorted_policies = sorted(policies, key=lambda p: p.weight, reverse=True)
    proposals: list[ChangeProposal] = []

    for finding in findings:
        proposal = _match_finding(finding, sorted_policies)
        if proposal:
            proposals.append(proposal)

    logger.info(
        "policy_evaluation_complete findings=%d matched=%d",
        len(findings),
        len(proposals),
    )
    return proposals


def _match_finding(
    finding: ResourceFinding,
    sorted_policies: list[Policy],
) -> ChangeProposal | None:
    for policy in sorted_policies:
        if _policy_matches(finding, policy):
            return _build_proposal(finding, policy)
    return None


def _policy_matches(finding: ResourceFinding, policy: Policy) -> bool:
    # Resource type filter
    if policy.resource_type != "*" and finding.resource_type != policy.resource_type:
        return False

    # Include scope
    if not _scope_includes(finding, policy.include):
        return False

    # Exclude scope
    if _scope_excludes(finding, policy.exclude):
        return False

    # Tier 1 conditions
    if not _tier1_matches(finding, policy.conditions):
        return False

    # Tier 2 conditions (only for registry-known types)
    if policy.conditions.metrics:
        if not _tier2_matches(finding, policy):
            return False

    return True


def _scope_includes(finding: ResourceFinding, scope: ScopeFilter) -> bool:
    if scope.cloud_platforms and finding.cloud not in scope.cloud_platforms:
        return False

    account = getattr(finding, "account_id", None) or getattr(finding, "cloud", "")
    if scope.accounts and account not in scope.accounts:
        return False

    if scope.regions and finding.region not in scope.regions:
        return False

    if scope.tags and not _tags_match(finding.tags, scope.tags):
        return False

    return True


def _scope_excludes(finding: ResourceFinding, scope: ScopeFilter) -> bool:
    if scope.cloud_platforms and finding.cloud in scope.cloud_platforms:
        return True

    account = getattr(finding, "account_id", None) or getattr(finding, "cloud", "")
    if scope.accounts and account in scope.accounts:
        return True

    if scope.regions and finding.region in scope.regions:
        return True

    if scope.tags and _tags_match(finding.tags, scope.tags):
        return True

    return False


def _tags_match(
    resource_tags: dict,
    scope_tags: tuple[dict[str, list[str]], ...],
) -> bool:
    """Return True if the resource has ALL tag conditions in scope_tags."""
    for tag_entry in scope_tags:
        for key, allowed_values in tag_entry.items():
            resource_value = resource_tags.get(key)
            if resource_value not in allowed_values:
                return False
    return True


def _tier1_matches(finding: ResourceFinding, cond: Condition) -> bool:
    if cond.min_estimated_monthly_cost_usd is not None:
        if finding.estimated_monthly_cost < cond.min_estimated_monthly_cost_usd:
            return False

    if cond.ai_priority is not None:
        if finding.priority.lower() not in cond.ai_priority:
            return False

    if cond.idle_days_min is not None:
        if finding.last_activity is None:
            # No activity timestamp — conservatively treat as not idle enough
            return False
        now = datetime.now(tz=timezone.utc)
        last = finding.last_activity
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        idle_days = (now - last).days
        if idle_days < cond.idle_days_min:
            return False

    return True


def _tier2_matches(finding: ResourceFinding, policy: Policy) -> bool:
    registry = get_registry()
    spec = registry.get(finding.resource_type)

    if spec is None:
        # Unknown type — skip Tier 2, log warning
        logger.warning(
            "tier2_skipped_unknown_type resource_type=%s policy_id=%s",
            finding.resource_type,
            policy.policy_id,
        )
        return True  # don't block on Tier 2 for unknown types

    metrics_summary = finding.metrics_summary or {}

    for mc in policy.conditions.metrics:
        value = metrics_summary.get(mc.metric)
        if value is None:
            # Metric not present in this finding — skip condition
            logger.debug(
                "tier2_metric_not_found metric=%s resource_id=%s policy_id=%s",
                mc.metric,
                finding.resource_id,
                policy.policy_id,
            )
            continue
        try:
            if not mc.evaluate(float(value)):
                return False
        except (TypeError, ValueError):
            logger.warning(
                "tier2_metric_not_numeric metric=%s value=%r resource_id=%s",
                mc.metric,
                value,
                finding.resource_id,
            )
            continue

    return True


def _build_proposal(finding: ResourceFinding, policy: Policy) -> ChangeProposal:
    from core.remediation import get_command

    runbook_text = (
        get_command(
            type_id=finding.resource_type,
            action=policy.action,
            resource_id=finding.resource_id,
            region=finding.region,
            account_id=getattr(finding, "account_id", None) or "",
        )
        or f"# No CLI template available for {finding.resource_type} / {policy.action}"
    )

    logger.info(
        "finding_matched_policy resource_id=%s resource_type=%s"
        " policy_id=%s action=%s weight=%s",
        finding.resource_id,
        finding.resource_type,
        policy.policy_id,
        policy.action,
        policy.weight,
    )

    return ChangeProposal(
        finding=finding,
        policy=policy,
        runbook=runbook_text,
        estimated_saving_usd=finding.estimated_monthly_cost,
    )
