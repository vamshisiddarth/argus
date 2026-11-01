"""
Tags through the Resource Groups Tagging API.

Resource Explorer only returns tags when the account's default view includes the
`tags` property. Without them the `environment: prod` and `argus-exempt`
safeguards silently do nothing, so when an inventory arrives with no tags at all
Argus asks the Tagging API instead. A failed call returns None: the tags are then
reported as unavailable, never as empty.
"""

from __future__ import annotations

from collections import defaultdict

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError

from adapters.aws.config import BOTO_TIMEOUT_CONFIG
from adapters.base import Resource

logger = structlog.get_logger(__name__)

_CHUNK = 100  # ResourceARNList accepts at most 100 ARNs


def fetch_tags(
    session: boto3.Session,
    resources: list[Resource],
    default_region: str = "us-east-1",
) -> dict[str, dict[str, str]] | None:
    """{arn: tags} for the resources the Tagging API knows; None if it failed."""
    by_region: dict[str, list[str]] = defaultdict(list)
    for r in resources:
        region = default_region if r.region in ("", "global") else r.region
        by_region[region].append(r.resource_id)

    out: dict[str, dict[str, str]] = {}
    try:
        for region, arns in sorted(by_region.items()):
            client = session.client(
                "resourcegroupstaggingapi",
                region_name=region,
                config=BOTO_TIMEOUT_CONFIG,
            )
            for start in range(0, len(arns), _CHUNK):
                chunk = arns[start : start + _CHUNK]
                response = client.get_resources(ResourceARNList=chunk)
                for mapping in response.get("ResourceTagMappingList", []):
                    tags = {t["Key"]: t["Value"] for t in mapping.get("Tags", [])}
                    if tags:
                        out[mapping["ResourceARN"]] = tags
    except (ClientError, BotoCoreError) as exc:
        logger.warning("tagging_api_failed", error=type(exc).__name__)
        return None
    return out
