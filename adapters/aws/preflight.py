"""
Pre-scan environment checks for AWS (read-only calls only).

Run before any LLM call. A `fail` means the scan would produce silently partial
or empty results; a `warn` means it can run but the report will be weaker.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from adapters.aws.config import BOTO_TIMEOUT_CONFIG
from core.models.preflight import PreflightCheck, PreflightResult

_RE_ACTIONS = (
    "resource-explorer-2:Search",
    "resource-explorer-2:GetView",
    "resource-explorer-2:GetDefaultView",
    "resource-explorer-2:ListIndexes",
    "resource-explorer-2:GetIndex",
)
_ACTION_LIST = ", ".join(_RE_ACTIONS)
_DOCS_HINT = "See docs/reference/iam-permissions.md for the minimal read-only policy."


def _is_admin_like(arn: str) -> bool:
    """Name-based heuristic only: no IAM calls are made to inspect policies."""
    for segment in arn.lower().split("/"):
        if "administrator" in segment or "fullaccess" in segment or segment == "admin":
            return True
    return False


def _code(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        return str(exc.response.get("Error", {}).get("Code", ""))
    return type(exc).__name__


def _denied(exc: Exception) -> bool:
    return _code(exc) in (
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedOperation",
        "UnauthorizedException",
    )


def run_preflight(
    session: boto3.Session,
    aggregator_region: str,
    account_id: str | None = None,
) -> PreflightResult:
    result = PreflightResult(account_id=account_id)
    add = result.checks.append

    # P1: who are we running as?
    try:
        ident = session.client("sts", config=BOTO_TIMEOUT_CONFIG).get_caller_identity()
        result.account_id = ident.get("Account") or account_id
        arn = ident.get("Arn", "unknown")
        if _is_admin_like(arn):
            add(
                PreflightCheck(
                    "P1_IDENTITY",
                    "warn",
                    f"Scanning as {arn}, which looks like an administrator role "
                    "(name-based check).",
                    "Run scans with a dedicated read-only role. " + _DOCS_HINT,
                )
            )
        else:
            add(PreflightCheck("P1_IDENTITY", "info", f"Scanning as {arn}."))
    except (ClientError, BotoCoreError) as exc:
        add(
            PreflightCheck(
                "P1_IDENTITY",
                "warn",
                f"Could not determine the caller identity ({_code(exc)}).",
                "Allow sts:GetCallerIdentity (it is always allowed unless denied).",
            )
        )

    re = session.client(
        "resource-explorer-2", region_name=aggregator_region, config=BOTO_TIMEOUT_CONFIG
    )

    # P2 + P3: can we list indexes, and is there an aggregator in the right region?
    try:
        indexes = _list_indexes(re)
    except (ClientError, BotoCoreError) as exc:
        add(
            PreflightCheck(
                "P2_RE_REACHABLE",
                "fail",
                "Cannot list Resource Explorer indexes "
                f"({_code(exc)}); missing resource-explorer-2:ListIndexes?",
                f"Grant {_ACTION_LIST}. " + _DOCS_HINT,
            )
        )
        return result
    add(PreflightCheck("P2_RE_REACHABLE", "ok", "Resource Explorer is reachable."))

    aggregators = [i for i in indexes if i.get("Type") == "AGGREGATOR"]
    here = [i for i in aggregators if i.get("Region") == aggregator_region]
    if not here:
        if aggregators:
            region = aggregators[0].get("Region")
            add(
                PreflightCheck(
                    "P3_AGGREGATOR_INDEX",
                    "fail",
                    f"No aggregator index in {aggregator_region}; one exists in "
                    f"{region}.",
                    f"Set RESOURCE_EXPLORER_REGION={region} (or create an "
                    f"aggregator index in {aggregator_region}).",
                )
            )
        else:
            kind = "only local indexes" if indexes else "no indexes"
            add(
                PreflightCheck(
                    "P3_AGGREGATOR_INDEX",
                    "fail",
                    f"Found {kind} and no aggregator index in {aggregator_region}. "
                    "Without an aggregator a search covers a single region and "
                    "silently misses the rest.",
                    f"Create an aggregator index in {aggregator_region} "
                    "(Resource Explorer > Settings > Aggregator index), or set "
                    "RESOURCE_EXPLORER_REGION to the region that has one.",
                )
            )
        return result
    add(PreflightCheck("P3_AGGREGATOR_INDEX", "ok", "Aggregator index found."))

    # P4: is the index finished populating?
    try:
        state = re.get_index().get("State", "UNKNOWN")
    except (ClientError, BotoCoreError):
        state = None
    if state in ("CREATING", "UPDATING"):
        add(
            PreflightCheck(
                "P4_INDEX_STATE",
                "warn",
                f"The index is {state}; results may be partial until it is ACTIVE.",
                "Wait for the index to become ACTIVE and re-run.",
            )
        )
    elif state:
        add(PreflightCheck("P4_INDEX_STATE", "ok", f"Index state is {state}."))

    # P5 + P6: default view exists and carries tags
    try:
        view_arn = re.get_default_view().get("ViewArn")
    except (ClientError, BotoCoreError) as exc:
        missing = _code(exc) == "ResourceNotFoundException"
        add(
            PreflightCheck(
                "P5_DEFAULT_VIEW",
                "fail",
                (
                    f"No default view in {aggregator_region}."
                    if missing
                    else f"Cannot read the default view ({_code(exc)})."
                ),
                (
                    "Create a default view that includes the tags property."
                    if missing
                    else f"Grant {_ACTION_LIST}."
                ),
            )
        )
        return result
    if not view_arn:
        add(
            PreflightCheck(
                "P5_DEFAULT_VIEW",
                "fail",
                f"No default view in {aggregator_region}.",
                "Create a default view that includes the tags property.",
            )
        )
        return result
    add(PreflightCheck("P5_DEFAULT_VIEW", "ok", "A default view exists."))

    try:
        props = re.get_view(ViewArn=view_arn)["View"].get("IncludedProperties", [])
        has_tags = any(p.get("Name") == "tags" for p in props)
    except (ClientError, BotoCoreError):
        has_tags = None
    if has_tags is False:
        add(
            PreflightCheck(
                "P6_VIEW_TAGS",
                "warn",
                "The default view does not include the tags property, so every "
                "resource looks untagged and the environment:prod and "
                "argus-exempt safeguards cannot work.",
                "Edit the default view and add the tags included property.",
            )
        )
    elif has_tags:
        add(PreflightCheck("P6_VIEW_TAGS", "ok", "The default view includes tags."))

    # P7: the actual search permission
    try:
        re.search(QueryString="*", MaxResults=1)
        add(PreflightCheck("P7_SEARCH_PERMISSION", "ok", "Search is permitted."))
    except (ClientError, BotoCoreError) as exc:
        if _denied(exc):
            add(
                PreflightCheck(
                    "P7_SEARCH_PERMISSION",
                    "fail",
                    f"Search was denied; the scan role needs {_ACTION_LIST}.",
                    _DOCS_HINT,
                )
            )
        else:
            add(
                PreflightCheck(
                    "P7_SEARCH_PERMISSION",
                    "fail",
                    f"Search failed ({_code(exc)}).",
                    "Check the aggregator index and default view, then retry.",
                )
            )
    return result


def _list_indexes(client) -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        kwargs = {"NextToken": token} if token else {}
        page = client.list_indexes(**kwargs)
        out.extend(page.get("Indexes", []))
        token = page.get("NextToken")
        if not token:
            return out
