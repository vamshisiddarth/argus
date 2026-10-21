"""Docs, templates and release metadata must agree with the code."""

from pathlib import Path

import pytest

from core.__version__ import __version__

ROOT = Path(__file__).resolve().parent.parent

RE_ACTIONS = [
    "resource-explorer-2:Search",
    "resource-explorer-2:GetView",
    "resource-explorer-2:GetDefaultView",
    "resource-explorer-2:ListViews",
    "resource-explorer-2:ListIndexes",
    "resource-explorer-2:GetIndex",
]

IAM_FILES = [
    "docs/reference/iam-permissions.md",
    "deploy/aws/single-account/template.yaml",
    "deploy/aws/multi-account/spoke-role.yaml",
    "deploy/aws/terraform/read-only-scan-role.tf",
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


@pytest.mark.parametrize("rel", IAM_FILES)
@pytest.mark.parametrize("action", RE_ACTIONS)
def test_resource_explorer_actions_documented(rel, action):
    assert action in _read(rel), f"{action} missing from {rel}"


def test_preflight_required_actions_are_all_listed_above():
    from adapters.aws.preflight import _RE_ACTIONS

    assert set(_RE_ACTIONS) <= set(RE_ACTIONS)


def test_version_is_0_7_0():
    assert __version__ == "0.7.0"


def test_changelog_has_release_heading_and_exit_codes():
    changelog = _read("CHANGELOG.md")
    assert "## v0.7.0" in changelog
    section = changelog.split("## v0.7.0", 1)[1].split("\n## v", 1)[0]
    assert "exit code 3" in section and "exit code 4" in section


def test_exit_codes_page_exists_and_is_in_nav():
    page = _read("docs/reference/exit-codes.md")
    for code in ("`2`", "`3`", "`4`"):
        assert code in page
    assert "reference/exit-codes.md" in _read("mkdocs.yml")


@pytest.mark.parametrize(
    "code",
    [
        "P1_IDENTITY",
        "P2_RE_REACHABLE",
        "P3_AGGREGATOR_INDEX",
        "P4_INDEX_STATE",
        "P5_DEFAULT_VIEW",
        "P6_VIEW_TAGS",
        "P7_SEARCH_PERMISSION",
    ],
)
def test_every_preflight_code_has_a_troubleshooting_entry(code):
    assert code in _read("docs/reference/troubleshooting.md")


def test_template_exposes_resource_explorer_region():
    template = _read("deploy/aws/single-account/template.yaml")
    assert "RESOURCE_EXPLORER_REGION:" in template
    assert "doesn't expose `RESOURCE_EXPLORER_REGION`" not in _read("docs/roadmap.md")


def test_new_env_vars_documented():
    env_vars = _read("docs/reference/env-vars.md")
    assert "STRICT_COVERAGE" in env_vars
    assert "ARGUS_SKIP_PREFLIGHT" in env_vars
