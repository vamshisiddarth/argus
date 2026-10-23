from __future__ import annotations

import json
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

from adapters.aws.config import BOTO_TIMEOUT_CONFIG
from adapters.base import Resource

logger = structlog.get_logger(__name__)

# Resource Explorer aggregator index lives in one region per account.
# This is created by our CloudFormation template. Users can override
# via RESOURCE_EXPLORER_REGION env var if their aggregator is elsewhere.
_SEARCH_RESULT_LIMIT = 1000
DEFAULT_AGGREGATOR_REGION = "us-east-1"

# -----------------------------------------------------------------------
# Non-billable resource type filter
# -----------------------------------------------------------------------
# These types never appear on an AWS bill (or cost < $0.01/month and carry
# no useful idle signal), so we strip them before the AI ever sees them.
# This cuts token count by 50-70% on a typical account.
#
# Rule: when in doubt, KEEP the type (the AI can always decide it's free).
# Only list types that are definitively free infrastructure primitives.
# -----------------------------------------------------------------------
_NON_BILLABLE_PREFIXES: frozenset[str] = frozenset(
    [
        # IAM — all objects are $0
        "aws::iam::",
        # CloudFormation — stacks/stacksets are metadata, not billed resources
        "aws::cloudformation::",
        # SSM parameters and documents ($0 for standard tier parameters)
        "aws::ssm::parameter",
        "aws::ssm::document",
        "aws::ssm::patchbaseline",
        "aws::ssm::maintenancewindow",
        "aws::ssm::resourcedatasync",
        "aws::ssm::association",
        # EC2 free infrastructure primitives
        "aws::ec2::routetable",
        "aws::ec2::subnet",
        "aws::ec2::networkacl",
        "aws::ec2::dhcpoptions",
        "aws::ec2::internetgateway",
        "aws::ec2::keypair",
        "aws::ec2::placementgroup",
        "aws::ec2::prefixlist",
        "aws::ec2::vpcpeeringconnection",
        # Config — rule/recorder metadata ($0)
        "aws::config::configrule",
        "aws::config::configurationrecorder",
        "aws::config::deliverychannel",
        "aws::config::conformancepack",
        # Lambda auxiliary objects (the function itself stays)
        "aws::lambda::eventsourcemapping",
        "aws::lambda::layerversion",
        # SNS subscriptions ($0 — the topic itself stays)
        "aws::sns::subscription",
        # CloudWatch alarms and dashboards ($0.10/alarm but no idle signal)
        "aws::cloudwatch::alarm",
        # Events — rules stay (EventBridge charges), but event buses default is free
        "aws::events::eventbus",
        # WAF — web ACL associations are metadata
        "aws::wafv2::webaclassociation",
        # Tagging — resource groups are free metadata
        "aws::resourcegroups::group",
        # Macie, GuardDuty, SecurityHub — findings/members are metadata
        "aws::guardduty::detector",
        "aws::guardduty::member",
        "aws::macie2::",
        "aws::securityhub::hub",
        "aws::securityhub::standard",
        # Service Catalog — products/portfolios are metadata
        "aws::servicecatalog::",
        # Organizations — accounts/OUs are metadata
        "aws::organizations::",
        # Access Analyzer
        "aws::accessanalyzer::analyzer",
    ]
)


def _is_billable(resource_type: str) -> bool:
    """Return True if a resource type could appear on an AWS bill."""
    lower = resource_type.lower()
    return not any(lower.startswith(prefix) for prefix in _NON_BILLABLE_PREFIXES)


def list_resources(
    session: boto3.Session,
    ignore_regions: list[str] | None = None,
    aggregator_region: str = DEFAULT_AGGREGATOR_REGION,
) -> list[Resource]:
    """See list_resources_with_status; returns only the resources."""
    return list_resources_with_status(session, ignore_regions, aggregator_region)[0]


def list_resources_with_status(
    session: boto3.Session,
    ignore_regions: list[str] | None = None,
    aggregator_region: str = DEFAULT_AGGREGATOR_REGION,
) -> tuple[list[Resource], bool]:
    """
    Return (resources, complete) for the whole account, minus ignore_regions.

    Uses the Resource Explorer v2 aggregator index. Search returns at most 1,000
    results per query, so when the first query comes back full the search is
    repeated once per region (plus "global") and the results are merged by ARN.
    `complete` is False if any single query still hit the limit.

    Requires: Resource Explorer aggregator index set up in aggregator_region.
    """
    client = session.client(
        "resource-explorer-2", region_name=aggregator_region, config=BOTO_TIMEOUT_CONFIG
    )
    ignore_set = set(ignore_regions) if ignore_regions else set()

    first, first_total = _search(client, "*", ignore_set)
    if first_total < _SEARCH_RESULT_LIMIT:
        logger.info(
            "resource_explorer_search_complete",
            total=len(first),
            ignored_regions=list(ignore_set),
        )
        return first, True

    logger.warning(
        "resource_explorer_search_limit",
        results=first_total,
        msg="Search reached the 1,000-result limit; searching region by region.",
    )
    by_arn = {r.resource_id: r for r in first}
    complete = True
    regions = set(session.get_available_regions("resource-explorer-2")) | {"global"}
    for region in sorted(regions - ignore_set):
        items, total = _search(client, f"region:{region}", ignore_set)
        by_arn.update({r.resource_id: r for r in items})
        if total >= _SEARCH_RESULT_LIMIT:
            complete = False
            logger.warning(
                "resource_explorer_region_limit",
                region=region,
                results=total,
                msg="Region still has 1,000+ results; some are not discovered.",
            )

    logger.info(
        "resource_explorer_search_complete",
        total=len(by_arn),
        ignored_regions=list(ignore_set),
        per_region=True,
        complete=complete,
    )
    return list(by_arn.values()), complete


def _search(
    client: Any, query: str, ignore_set: set[str]
) -> tuple[list[Resource], int]:
    """One paginated Search. Returns (billable resources, raw result count)."""
    resources: list[Resource] = []
    raw_total = 0
    try:
        paginator = client.get_paginator("search")
        for page in paginator.paginate(QueryString=query):
            for raw in page.get("Resources", []):
                raw_total += 1
                if raw.get("Region") in ignore_set:
                    continue
                if not _is_billable(raw.get("ResourceType", "")):
                    continue
                parsed = _parse_resource(raw)
                if parsed:
                    resources.append(parsed)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "AccessDeniedException":
            raise PermissionError(
                "Argus IAM role is missing resource-explorer-2:Search permission."
            ) from exc
        if code in ("ResourceNotFoundException", "ValidationException"):
            raise RuntimeError(
                "No Resource Explorer aggregator index found. "
                "Deploy the Argus CloudFormation template to create one, "
                "or enable Resource Explorer manually in the AWS console."
            ) from exc
        raise
    return resources, raw_total


def _parse_resource(raw: dict[str, Any]) -> Resource | None:
    arn = raw.get("Arn", "")
    resource_type = raw.get("ResourceType", "")
    region = raw.get("Region", "")

    if not arn or not resource_type:
        return None

    tags = _parse_tags(raw.get("Properties", []))

    return Resource(
        resource_id=arn,
        resource_type=resource_type,
        cloud="aws",
        region=region,
        name=tags.get("Name"),
        tags=tags,
    )


def _parse_tags(properties: list[dict[str, Any]]) -> dict[str, str]:
    """
    Resource Explorer returns tags as JSON-encoded string in Properties.
    Example: {"Name": "tags", "Data": "[{\"Key\":\"Env\",\"Value\":\"prod\"}]"}
    """
    for prop in properties:
        if prop.get("Name") == "tags":
            try:
                tag_list = json.loads(prop.get("Data", "[]"))
                return {
                    t["Key"]: t["Value"]
                    for t in tag_list
                    if "Key" in t and "Value" in t
                }
            except (json.JSONDecodeError, TypeError):
                return {}
    return {}
