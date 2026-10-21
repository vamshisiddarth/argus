from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from adapters.aws.preflight import _is_admin_like, run_preflight

READONLY_ARN = "arn:aws:sts::123456789012:assumed-role/argus-scan/session"
ADMIN_ARN = "arn:aws:sts::123456789012:assumed-role/AdministratorAccess/me"


def _err(code, op="Op"):
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


def _session(
    *,
    arn=READONLY_ARN,
    indexes=None,
    index_state="ACTIVE",
    default_view="arn:view",
    view_props=("tags",),
    list_indexes_error=None,
    get_default_view_error=None,
    search_error=None,
):
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012", "Arn": arn}

    re = MagicMock()
    if list_indexes_error:
        re.list_indexes.side_effect = list_indexes_error
    else:
        re.list_indexes.return_value = {
            "Indexes": (
                indexes
                if indexes is not None
                else [{"Region": "us-east-1", "Type": "AGGREGATOR", "Arn": "arn:idx"}]
            )
        }
    re.get_index.return_value = {"State": index_state, "Type": "AGGREGATOR"}
    if get_default_view_error:
        re.get_default_view.side_effect = get_default_view_error
    else:
        re.get_default_view.return_value = {"ViewArn": default_view}
    re.get_view.return_value = {
        "View": {"IncludedProperties": [{"Name": n} for n in view_props]}
    }
    if search_error:
        re.search.side_effect = search_error
    else:
        re.search.return_value = {"Resources": []}

    session = MagicMock()
    session.client.side_effect = lambda name, **kw: {
        "sts": sts,
        "resource-explorer-2": re,
    }[name]
    return session


def _by_code(result):
    return {c.code: c for c in result.checks}


def test_all_good_has_no_failures_or_warnings():
    result = run_preflight(_session(), "us-east-1")

    assert result.failed == []
    assert result.warnings == []
    assert result.account_id == "123456789012"
    assert _by_code(result)["P1_IDENTITY"].status == "info"
    assert READONLY_ARN in _by_code(result)["P1_IDENTITY"].message


@pytest.mark.parametrize(
    ("arn", "admin"),
    [
        (ADMIN_ARN, True),
        ("arn:aws:iam::1:role/PowerUserFullAccess", True),
        ("arn:aws:iam::1:role/administrator", True),
        (READONLY_ARN, False),
        ("arn:aws:iam::1:role/admin-panel-reader", False),
    ],
)
def test_admin_heuristic(arn, admin):
    assert _is_admin_like(arn) is admin


def test_admin_role_warns_and_names_arn():
    result = run_preflight(_session(arn=ADMIN_ARN), "us-east-1")

    check = _by_code(result)["P1_IDENTITY"]
    assert check.status == "warn"
    assert ADMIN_ARN in check.message
    assert "read-only" in check.fix
    assert result.failed == []


def test_list_indexes_access_denied_fails_p2_and_names_action():
    result = run_preflight(
        _session(list_indexes_error=_err("AccessDeniedException")), "us-east-1"
    )

    check = _by_code(result)["P2_RE_REACHABLE"]
    assert check.status == "fail"
    assert "resource-explorer-2:ListIndexes" in check.message
    assert "P3_AGGREGATOR_INDEX" not in _by_code(result)


def test_local_only_index_fails_p3_with_region_and_fix():
    local = [{"Region": "us-east-1", "Type": "LOCAL", "Arn": "arn:idx"}]
    result = run_preflight(_session(indexes=local), "us-east-1")

    check = _by_code(result)["P3_AGGREGATOR_INDEX"]
    assert check.status == "fail"
    assert "aggregator" in check.message.lower()
    assert "us-east-1" in check.message
    assert check.fix


def test_aggregator_in_other_region_points_at_env_var():
    idx = [{"Region": "eu-west-1", "Type": "AGGREGATOR", "Arn": "arn:idx"}]
    result = run_preflight(_session(indexes=idx), "us-east-1")

    check = _by_code(result)["P3_AGGREGATOR_INDEX"]
    assert check.status == "fail"
    assert "RESOURCE_EXPLORER_REGION=eu-west-1" in check.fix


def test_no_indexes_at_all_fails_p3():
    result = run_preflight(_session(indexes=[]), "us-east-1")
    assert _by_code(result)["P3_AGGREGATOR_INDEX"].status == "fail"


@pytest.mark.parametrize("state", ["CREATING", "UPDATING"])
def test_populating_index_warns_p4(state):
    result = run_preflight(_session(index_state=state), "us-east-1")

    check = _by_code(result)["P4_INDEX_STATE"]
    assert check.status == "warn"
    assert "partial" in check.message


def test_missing_default_view_fails_p5():
    result = run_preflight(
        _session(get_default_view_error=_err("ResourceNotFoundException")),
        "us-east-1",
    )

    assert _by_code(result)["P5_DEFAULT_VIEW"].status == "fail"
    assert "P6_VIEW_TAGS" not in _by_code(result)


def test_view_without_tags_warns_p6_and_mentions_safeguards():
    result = run_preflight(_session(view_props=()), "us-east-1")

    check = _by_code(result)["P6_VIEW_TAGS"]
    assert check.status == "warn"
    assert "argus-exempt" in check.message


def test_search_access_denied_fails_p7_with_actions():
    result = run_preflight(
        _session(search_error=_err("AccessDeniedException")), "us-east-1"
    )

    check = _by_code(result)["P7_SEARCH_PERMISSION"]
    assert check.status == "fail"
    for action in ("Search", "GetView", "GetDefaultView", "ListIndexes"):
        assert f"resource-explorer-2:{action}" in check.message


def test_every_failure_has_a_fix_and_serialises():
    result = run_preflight(
        _session(indexes=[{"Region": "us-east-1", "Type": "LOCAL"}]), "us-east-1"
    )

    assert result.failed
    assert all(c.fix for c in result.failed)
    d = result.to_dict()
    assert d["skipped"] is False
    assert {"code", "status", "message", "fix"} <= set(d["checks"][0])


def test_sts_failure_does_not_crash_preflight():
    session = _session()
    sts = MagicMock()
    sts.get_caller_identity.side_effect = _err("AccessDenied")
    original = session.client.side_effect
    session.client.side_effect = lambda name, **kw: (
        sts if name == "sts" else original(name, **kw)
    )

    result = run_preflight(session, "us-east-1")

    assert _by_code(result)["P1_IDENTITY"].status == "warn"
    assert result.account_id is None
    assert result.failed == []
