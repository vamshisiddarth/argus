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
    "deploy/aws/read-only-scan-role.yaml",
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
        "P8_COST_DATA",
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


def test_anthropic_dependency_has_an_upper_bound():
    import re

    line = next(
        line for line in _read("pyproject.toml").splitlines() if '"anthropic' in line
    )
    assert re.search(r"<\s*\d", line), f"no upper bound: {line.strip()}"


def test_new_ai_settings_documented():
    env_vars = _read("docs/reference/env-vars.md")
    assert "AI_MAX_TOKENS" in env_vars
    assert "AI_TIMEOUT_SECONDS" in env_vars


def test_changelog_describes_the_customer_feedback_features():
    section = _read("CHANGELOG.md").split("## v0.7.0", 1)[1].split("\n## v", 1)[0]
    for item in (
        "--expect-account",
        "waste_by_confidence",
        "baseline rules",
        "per-region discovery",
        "ai_max_tokens",
        "known limitations",
    ):
        assert item in section.lower(), item
    assert "Known gaps (tracked for 0.7.1" not in section


def test_every_baseline_rule_is_documented():
    from core.baseline.rules import RULES

    page = _read("docs/concepts/baseline-rules.md")
    for rule in RULES:
        assert rule.rule_id in page, rule.rule_id
        assert f"{rule.list_price_usd:.2f}" in page
    assert "concepts/baseline-rules.md" in _read("mkdocs.yml")


def test_new_settings_are_documented():
    env_vars = _read("docs/reference/env-vars.md")
    for var in ("ARGUS_BASELINE_RULES", "ARGUS_EXPECT_ACCOUNT", "BEDROCK_MAX_TOKENS"):
        assert var in env_vars, var


def test_report_schema_documents_the_new_fields():
    schema = _read("docs/reference/report-schema.md")
    for key in (
        "waste_by_confidence",
        "total_is_estimate",
        "discovery_complete",
        "detected_by",
        "confidence",
        "cost_basis",
        "max_resources_source",
    ):
        assert key in schema, key


def test_roadmap_no_longer_lists_fixed_gaps():
    assert "BEDROCK_MAX_TOKENS` is ignored" not in _read("docs/roadmap.md")


def test_day_window_settings_are_documented():
    env_vars = _read("docs/reference/env-vars.md")
    readme = _read("README.md")
    schema = _read("docs/reference/report-schema.md")
    changelog = _read("CHANGELOG.md").split("## v0.7.0", 1)[1].split("\n## v", 1)[0]
    for var in ("COST_LOOKBACK_DAYS", "ACTIVITY_LOOKBACK_DAYS"):
        assert var in env_vars, var
    for flag in ("--cost-days", "--activity-days"):
        assert flag in readme and flag in changelog, flag
    assert "activity_lookback_days" in schema
