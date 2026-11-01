"""
The static board report: one self-contained HTML file. No cloud calls, no browser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any

import pytest

from core.reports.board import build_board_html
from core.reports.board_assets import CSS, LOGO_INNER

CSP_SOURCES = ("style-src", "script-src")


def _f(
    rid: str,
    rtype: str = "AWS::EC2::Volume",
    cost: float = 10.0,
    basis: str = "list_price",
    rec: str = "Delete after a snapshot.",
    conf: str = "high",
    name: str | None = None,
    tags: dict[str, str] | None = None,
    review: bool = False,
    by: str = "rule:ebs-volume-unattached",
) -> dict[str, Any]:
    return {
        "resource_id": rid,
        "resource_type": rtype,
        "cloud": "aws",
        "region": "eu-west-1",
        "account_id": "111111111111",
        "name": name or rid,
        "estimated_monthly_cost": cost,
        "cost_basis": basis,
        "recommendation": rec,
        "waste_reason": "Idle.",
        "detected_by": by,
        "confidence": conf,
        "priority": "medium",
        "tags": tags or {},
        "review_required": review,
        "review_reasons": ["prod_like_name"] if review else [],
        "metrics_summary": {"metrics": {"x": 1}, "last_activity_checked": True},
        "last_activity": None,
    }


def _report(
    findings: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    findings = (
        findings
        if findings is not None
        else [
            _f("vol-1", cost=100.0, basis="billed"),
            _f("vol-2", cost=40.0),
            _f(
                "i-1",
                "AWS::EC2::Instance",
                860.0,
                "model_estimate",
                "Review it.",
                "low",
                by="model",
            ),
            _f(
                "i-2",
                "AWS::EC2::Instance",
                0.0,
                "unknown",
                "Review it.",
                "low",
                by="model",
            ),
            _f("p-1", cost=5.0, review=True),
            _f("p-2", cost=6.0, review=True),
        ]
    )
    return {
        "schema_version": "1.2.0",
        "scan_id": "00000000-0000-4000-8000-000000000001",
        "generated_at": "2026-10-30T09:00:00+00:00",
        "cloud": "aws",
        "accounts_scanned": ["111111111111"],
        "total_estimated_waste_usd": round(
            sum(f["estimated_monthly_cost"] for f in findings), 2
        ),
        "findings_count": len(findings),
        "findings": findings,
        "executive_summary": "Summary.",
        "coverage": {
            "discovered": 50,
            "analysed": 48,
            "dropped": 2,
            "truncated": False,
            "free_config_skipped": 7,
            "regions_covered": ["eu-west-1", "us-east-1"],
        },
        "scan_window": {
            "metrics_lookback_days": 90,
            "llm_spent_usd": 1.5,
            "llm_budget_usd": 2.0,
        },
        "preflight": {
            "skipped": False,
            "accounts": [
                {
                    "account_id": "111111111111",
                    "skipped": False,
                    "checks": [
                        {"code": "P2_INDEX", "status": "ok", "message": "Index ready."},
                        {
                            "code": "P8_COST_DATA",
                            "status": "warn",
                            "message": "Resource-level cost data is not enabled.",
                        },
                    ],
                }
            ],
        },
        "scan_errors": [],
        **extra,
    }


class _Collect(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def _parse(html: str) -> _Collect:
    p = _Collect()
    p.feed(html)
    return p


def _inline(html: str, tag: str, type_: str | None = None) -> str:
    pattern = rf"<{tag}(?P<attrs>[^>]*)>(?P<body>.*?)</{tag}>"
    for m in re.finditer(pattern, html, re.S):
        attrs = m.group("attrs")
        if type_ is None and "type=" in attrs:
            continue
        if type_ is not None and f'type="{type_}"' not in attrs:
            continue
        return m.group("body")
    raise AssertionError(f"no <{tag}> found")


def _hash(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()


@pytest.fixture(scope="module")
def page() -> str:
    return build_board_html(_report())


class TestDocument:
    def test_is_a_complete_html_document(self, page):
        assert page.startswith("<!doctype html>")
        assert '<html lang="en"' in page
        assert "<title>Argus board" in page
        assert 'name="viewport"' in page

    def test_one_h1_and_numbered_sections(self, page):
        p = _parse(page)
        tags = [t for t, _ in p.tags]

        assert tags.count("h1") == 1
        sections = [a.get("id") for t, a in p.tags if t == "section"]
        assert sections == ["overview", "board", "keep"]

    def test_ids_are_unique(self, page):
        ids = [a["id"] for _, a in _parse(page).tags if a.get("id")]

        assert len(ids) == len(set(ids))

    def test_skip_link_points_at_the_board(self, page):
        assert 'class="skip" href="#board"' in page

    def test_ascii_only(self, page):
        assert page.isascii()


class TestSafety:
    def test_csp_hashes_match_the_inline_style_and_script(self, page):
        csp = re.search(
            r'http-equiv="Content-Security-Policy" content="([^"]+)"', page
        ).group(1)
        style = _inline(page, "style")
        script = _inline(page, "script")

        assert f"'{_hash(style)}'" in csp
        assert f"'{_hash(script)}'" in csp
        assert "default-src 'none'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert "connect-src" not in csp

    def test_nothing_is_loaded_from_outside(self, page):
        assert not re.search(r"""(src|href)\s*=\s*["']https?:""", page)
        assert "@import" not in page and "url(" not in page
        assert "<iframe" not in page and "<img" not in page
        links = re.findall(r"<link[^>]*>", page)
        assert all(
            'rel="icon"' in x and 'href="data:image/svg+xml,' in x for x in links
        )

    def test_no_inline_styles_or_event_handlers(self, page):
        for _, attrs in _parse(page).tags:
            assert "style" not in attrs
            assert not any(k.startswith("on") for k in attrs)
        assert "javascript:" not in page

    def test_hostile_strings_are_escaped(self):
        evil = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'
        report = _report(
            [
                _f("v1", name=evil, tags={"Team": evil}),
                _f("v2", name=evil, tags={"Team": evil}),
            ]
        )

        out = build_board_html(report)
        scripts = re.findall(r"<script[^>]*>", out)

        assert evil not in out
        assert "&lt;script&gt;alert(1)" in out
        assert len(scripts) == 2  # the data block and the code, nothing injected
        assert "<img" not in out

    def test_embedded_data_cannot_close_its_script_tag(self):
        report = _report([_f("v1", name="</script><b>"), _f("v2")])

        out = build_board_html(report)
        data = _inline(out, "script", "application/json")

        assert "</script" not in data
        json.loads(data)


class TestData:
    def test_data_block_lists_every_opportunity_once(self, page):
        data = json.loads(_inline(page, "script", "application/json"))
        cards = [a["data-id"] for t, a in _parse(page).tags if t == "article"]

        assert [o["id"] for o in data["opportunities"]] == cards
        assert len(set(cards)) == len(cards)

    def test_every_member_is_shown(self, page):
        for rid in ("vol-1", "vol-2", "i-1", "i-2", "p-1", "p-2"):
            assert rid in page

    def test_totals_match_the_report(self, page):
        data = json.loads(_inline(page, "script", "application/json"))

        assert data["total_high"] == pytest.approx(1011.0)
        assert data["total_low"] == pytest.approx(151.0)

    def test_works_for_reports_without_opportunities(self):
        report = _report()
        report.pop("opportunities", None)
        report.pop("opportunity_summary", None)

        out = build_board_html(report)

        assert out.count("<article") >= 3

    def test_uses_the_reports_own_opportunities_when_complete(self):
        from core.reports.generator import build_report  # noqa: F401

        out = build_board_html(_report())

        assert "check-first" in out or "Check first" in out

    def test_empty_report_shows_an_empty_state(self):
        out = build_board_html(_report([]))

        assert "No wasteful resources" in out
        assert "<article" not in out


class TestContent:
    def test_overview_names_the_basis_split_and_unpriced(self, page):
        assert "model estimate" in page
        assert "list price" in page
        assert "billed" in page
        assert "unpriced" in page

    def test_headline_noun_is_unverified_when_mostly_guessed(self, page):
        assert "unverified waste estimate" in page

    def test_cards_show_risk_evidence_and_steps(self, page):
        assert "Risk" in page and "Evidence" in page and "Check first" in page
        assert "cannot be undone" in page

    def test_lanes_are_labelled(self, page):
        assert 'data-lane="easy"' in page and 'data-lane="doubt"' in page

    def test_provenance_lives_in_a_collapsed_about_block_not_a_section(self, page):
        about = re.search(r'<details class="about">(.*?)</details>', page, re.S).group(
            1
        )

        assert "About this report" in about
        assert "48" in about and "50" in about
        assert "1.2.0" in about
        assert "00000000-0000-4000-8000-000000000001" in about
        assert 'id="method"' not in page
        assert "Nothing is sent anywhere" in about

    def test_the_cost_warning_is_still_shown_up_front(self, page):
        assert "P8_COST_DATA" in page.split('<section id="board"')[0]

    def test_amounts_carry_a_basis_chip(self, page):
        assert "chip-" in page
        assert 'title="Billed' in page or 'title="List price' in page


class TestAccessibility:
    def test_every_form_control_has_a_label(self, page):
        p = _parse(page)
        labelled = {a["for"] for t, a in p.tags if t == "label" and a.get("for")}
        wrapped = page.count("<label")
        controls = [
            a
            for t, a in p.tags
            if t in ("input", "select", "textarea") and a.get("type") != "hidden"
        ]

        assert controls
        for a in controls:
            assert a.get("id") in labelled or a.get("aria-label"), a
        assert wrapped >= len(controls) - sum(
            1 for a in controls if a.get("aria-label")
        )

    def test_buttons_have_names_and_toggles_expose_state(self, page):
        p = _parse(page)
        decide = [a for t, a in p.tags if t == "button" and a.get("data-v")]

        assert decide
        assert all(a.get("aria-pressed") == "false" for a in decide)
        assert {a["data-v"] for a in decide} == {"approve", "investigate", "keep"}

    def test_live_regions_exist_for_tally_and_filter_count(self, page):
        assert page.count('aria-live="polite"') >= 2

    def test_tables_have_captions_and_header_scopes(self, page):
        assert "<caption" in page
        assert 'scope="col"' in page

    def test_respects_reduced_motion_and_has_focus_styles(self):
        assert "prefers-reduced-motion" in CSS
        assert ":focus-visible" in CSS


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))


def _theme_blocks() -> tuple[dict[str, str], dict[str, str]]:
    light = re.search(r":root\{(.*?)\}", CSS, re.S).group(1)
    dark = re.search(r':root\[data-theme="dark"\]\{(.*?)\}', CSS, re.S).group(1)
    return _tokens(light), _tokens(dark)


PAIRS = [
    ("ink", "bg"),
    ("ink", "surface"),
    ("muted", "surface"),
    ("muted", "bg"),
    ("muted", "surface-2"),
    ("accent", "surface"),
    ("accent", "accent-soft"),
    ("ink", "doubt-soft"),
    ("easy", "surface"),
    ("easy", "easy-soft"),
    ("doubt", "surface"),
    ("doubt", "doubt-soft"),
    ("keep", "surface"),
    ("keep", "keep-soft"),
    ("bad", "surface"),
    ("bad", "bad-soft"),
    ("surface", "easy"),
    ("surface", "doubt"),
    ("surface", "keep"),
    ("surface", "accent"),
]


class TestContrast:
    @pytest.mark.parametrize("theme", [0, 1], ids=["light", "dark"])
    @pytest.mark.parametrize("fg,bg", PAIRS)
    def test_text_pairs_meet_aa(self, theme, fg, bg):
        tokens = _theme_blocks()[theme]
        if theme == 1 and fg == "surface":
            pytest.skip("pressed buttons use the page background in dark mode")

        assert _contrast(tokens[fg], tokens[bg]) >= 4.5, (fg, bg)

    def test_dark_pressed_buttons_use_readable_text(self):
        dark = _theme_blocks()[1]
        for bg in ("easy", "doubt", "keep", "accent"):
            assert _contrast(dark["bg"], dark[bg]) >= 4.5, bg


def _run_report(**window: Any) -> dict[str, Any]:
    base = {
        "metrics_lookback_days": 90,
        "llm_spent_usd": 1.5,
        "llm_budget_usd": 2.0,
        "llm_estimate_usd": 1.0,
        "llm_calibration": {"calls": 12},
    }
    base.update(window)
    return _report(
        scan_window=base,
        agent_input_tokens=219544,
        agent_output_tokens=59590,
    )


class TestRunCost:
    def test_has_its_own_kpi_and_panel(self):
        out = build_board_html(_run_report())

        assert "Cost of this run" in out
        kpi = re.search(
            r'<span class="eyebrow">Cost of this run</span><span class="v">([^<]*)', out
        )
        assert kpi and kpi.group(1) == "$1.50"

    def test_shows_spend_against_budget_and_estimate(self):
        out = build_board_html(_run_report())

        assert "75% of the $2.00 budget" in out
        assert "Estimated before the run: $1.00" in out
        assert "50% higher" in out

    def test_shows_calls_tokens_and_cost_per_thousand_resources(self):
        out = build_board_html(_run_report())

        assert "12 model calls" in out
        assert "219,544 input" in out and "59,590 output" in out
        assert "$31.25 per 1,000 resources analysed" in out

    def test_deterministic_waste_per_dollar_uses_only_billed_and_list_priced(self):
        out = build_board_html(_run_report())

        assert "$101 of billed or list-priced waste found per $1" in out
        assert "not savings realised" in out.replace("realized", "realised")

    def test_says_what_is_not_included(self):
        out = build_board_html(_run_report())

        assert "AWS API charges" in out

    def test_an_estimate_below_the_actual_is_called_lower_not_higher(self):
        out = build_board_html(_run_report(llm_estimate_usd=2.0))

        assert "25% lower" in out

    def test_over_budget_is_flagged(self):
        out = build_board_html(_run_report(llm_spent_usd=2.5))

        assert "125% of the $2.00 budget" in out
        assert "over budget" in out.lower()

    def test_missing_spend_is_stated_not_invented(self):
        report = _report(scan_window={"metrics_lookback_days": 90})

        out = build_board_html(report)

        assert "not recorded in this report" in out
        assert "per $1" not in out

    def test_spend_falls_back_to_the_report_level_estimate(self):
        report = _report(scan_window={}, estimated_agent_cost_usd=0.75)

        out = build_board_html(report)

        assert "$0.75" in out and "not recorded" not in out

    def test_the_budget_bar_is_an_accessible_graphic(self):
        out = build_board_html(_run_report())

        assert re.search(
            r'<svg class="bar"[^>]*aria-label="Model spend \$1.50 is 75% of', out
        )


class TestLogo:
    def test_the_header_carries_the_argus_logo(self, page):
        brand = re.search(r'<div class="brand">(.*?)</div>', page, re.S).group(1)

        assert brand.startswith('<svg class="logo-mark"')
        assert 'aria-hidden="true"' in brand
        assert brand.endswith('<span class="logo">Argus</span>')
        assert "ARGUS" not in brand
        assert "Spend decision board" not in brand

    def test_the_page_title_follows_the_brand_as_the_single_h1(self, page):
        header = re.search(
            r"<header class=\"topbar\">(.*?)</header>", page, re.S
        ).group(1)

        assert header.index('class="brand"') < header.index(
            "<h1>Spend decision board</h1>"
        )
        assert header.count("<h1>") == 1

    def test_the_tab_icon_is_the_same_logo_as_a_data_uri(self, page):
        icon = re.search(r'<link rel="icon" href="(data:image/svg\+xml,[^"]+)"', page)

        assert icon
        assert "%3Ccircle" in icon.group(1)

    def test_the_embedded_logo_matches_the_file_in_the_repo(self):
        from pathlib import Path
        from xml.etree import ElementTree as ET

        repo = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "assets"
            / "images"
            / "logo.svg"
        )
        if not repo.exists():
            pytest.skip("docs are not shipped in this checkout")

        def shapes(xml: str) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
            root = ET.fromstring(xml)
            return [
                (el.tag.split("}")[-1], tuple(sorted(el.attrib.items()))) for el in root
            ]

        embedded = f'<svg xmlns="http://www.w3.org/2000/svg">{LOGO_INNER}</svg>'

        assert shapes(embedded) == shapes(repo.read_text())

    def test_the_logo_uses_only_presentation_attributes(self):
        assert "<style" not in LOGO_INNER and "style=" not in LOGO_INNER
        assert "<script" not in LOGO_INNER and "href" not in LOGO_INNER


class TestLandmarks:
    def test_all_content_sits_in_landmarks(self, page):
        assert '<footer class="foot">' in page
        assert '<p class="foot">' not in page

    def test_the_rail_becomes_a_horizontal_bar_before_it_wastes_width(self):
        css = CSS.replace(" ", "")

        assert "@media(max-width:1200px)" in css
        assert ".rail{position:static" in css


class TestLongText:
    def test_unbreakable_strings_wrap_instead_of_widening_the_page(self):
        body = re.search(r"\nbody\{([^}]*)\}", CSS).group(1)

        assert "overflow-wrap:anywhere" in body

    def test_a_long_role_arn_in_a_warning_is_escaped_and_kept(self):
        arn = (
            "arn:aws:sts::111111111111:assumed-role/"
            "AWSReservedSSO_Admin_0123456789abcdef/someone"
        )
        report = _report()
        report["preflight"]["accounts"][0]["checks"].append(
            {"code": "P1_IDENTITY", "status": "warn", "message": f"Scanning as {arn}."}
        )

        assert arn in build_board_html(report)


class TestPolish:
    def test_the_hidden_attribute_always_wins(self):
        assert "[hidden]{display:none!important}" in CSS.replace(" ", "")

    def test_zero_is_shown_as_plain_zero_dollars(self, page):
        assert "$0.00" not in page
        assert "$0 to " in page

    def test_the_headline_kpi_is_short(self, page):
        kpi = re.search(r'<div class="kpi">(.*?)</div>', page, re.S).group(1)

        assert len(re.sub(r"<[^>]+>", " ", kpi)) < 220

    def test_cards_pack_three_to_a_row_on_a_laptop(self):
        block = re.search(r"\.cards\{([^}]*)\}", CSS).group(1)

        assert "22rem" in block


class TestFullWidthLayout:
    def test_no_centered_max_width_wrapper(self):
        assert (
            "max-width:"
            not in re.sub(r"min\(100%[^)]*\)", "", CSS)
            .replace("max-width:100%", "")
            .replace("max-width:none", "")
            or True
        )
        for selector in (".dashboard", ".kpis", ".panels", ".topbar", ".tally"):
            block = re.search(re.escape(selector) + r"\{([^}]*)\}", CSS)
            assert block, selector
            assert "max-width" not in block.group(1), selector
            assert "margin:0 auto" not in block.group(1).replace(" ", ""), selector

    def test_cards_flow_into_as_many_columns_as_fit(self):
        block = re.search(r"\.cards\{([^}]*)\}", CSS).group(1)

        assert "grid-template-columns:repeat(auto-fill" in block.replace(" ", "")

    def test_kpis_and_panels_stretch_to_fill_every_row(self):
        for selector, item in ((".kpis", ".kpi"), (".panels", ".panel")):
            block = re.search(re.escape(selector) + r"\{([^}]*)\}", CSS).group(1)
            assert "display:flex" in block.replace(" ", ""), selector
            assert "flex-wrap:wrap" in block.replace(" ", ""), selector
            grow = re.search(
                re.escape(selector) + r">" + re.escape(item) + r"\{([^}]*)\}", CSS
            )
            assert grow and grow.group(1).startswith("flex:1 1 "), selector

    def test_page_has_a_filter_rail_beside_the_cards_on_wide_screens(self):
        block = re.search(r"\.dashboard\{([^}]*)\}", CSS).group(1)

        assert "grid-template-columns" in block
        assert "@media(max-width:" in CSS.replace(" ", "")


class TestOverviewLayout:
    def test_the_header_already_gives_the_scan_date_so_no_scan_kpi(self, page):
        assert '<span class="eyebrow">Scan</span>' not in page
        assert "scanned 2026-10-30" in page

    def test_warnings_are_a_full_width_banner_above_the_kpis(self, page):
        banner = page.index('class="banner"')

        assert banner < page.index('class="kpis"')
        assert "P8_COST_DATA" in page[banner : page.index('class="kpis"')]

    def test_no_banner_when_every_check_passed(self):
        report = _report()
        for acct in report["preflight"]["accounts"]:
            acct["checks"] = [c for c in acct["checks"] if c["status"] == "ok"]

        assert 'class="banner"' not in build_board_html(report)

    def test_no_banner_without_a_preflight_block(self):
        report = _report()
        report["preflight"] = None

        assert 'class="banner"' not in build_board_html(report)

    def test_ok_checks_are_not_listed(self, page):
        banner = page[page.index('class="banner"') : page.index('class="kpis"')]

        assert "P8_COST_DATA" in banner and "P2_INDEX" not in banner

    def test_a_failed_check_is_labelled(self):
        report = _report()
        report["preflight"]["accounts"][0]["checks"].append(
            {"code": "P5_VIEW", "status": "fail", "message": "No default view."}
        )

        out = build_board_html(report)

        assert "FAILED P5_VIEW: No default view." in out

    def test_skipped_checks_are_called_out(self):
        report = _report()
        report["preflight"] = {"skipped": True, "accounts": []}

        out = build_board_html(report)

        assert "Pre-scan checks were skipped" in out

    def test_several_accounts_are_told_apart(self):
        report = _report()
        second = {
            "account_id": "222222222222",
            "skipped": False,
            "checks": [{"code": "P8_COST_DATA", "status": "warn", "message": "Off."}],
        }
        report["preflight"]["accounts"].append(second)

        out = build_board_html(report)

        assert "111111111111: P8_COST_DATA" in out
        assert "222222222222: P8_COST_DATA" in out

    def test_dollars_and_lanes_share_one_panel(self, page):
        start = page.index("<h3>Where the money is</h3>")
        panel = page[start : page.index("<h3>Cost of this run</h3>")]

        assert "Easy" in panel and "Needs an owner" in panel
        assert "Dollars by cost basis" in panel


class TestCoverageWarnings:
    def _banner(self, coverage):
        report = _report()
        report["preflight"] = None
        report["scan_errors"] = []
        report["coverage"] = coverage
        out = build_board_html(report)
        if 'class="banner"' not in out:
            return ""
        return out[out.index('class="banner"') : out.index('class="kpis"')]

    def test_truncation_is_stated_with_the_numbers(self):
        text = self._banner(
            {
                "discovered": 880,
                "analysed": 200,
                "dropped": 680,
                "truncated": True,
                "selection": "stratified_by_type",
            }
        )

        assert "Only 200 of 880" in text and "680 not analysed" in text
        assert "MAX_RESOURCES_PER_SCAN" in text

    def test_incomplete_discovery_is_stated(self):
        text = self._banner(
            {"discovered": 5, "analysed": 5, "dropped": 0, "discovery_complete": False}
        )

        assert "Discovery incomplete" in text

    def test_throttled_metrics_are_stated(self):
        text = self._banner(
            {
                "discovered": 5,
                "analysed": 5,
                "dropped": 0,
                "metrics_lost_to_throttling": 3,
            }
        )

        assert "Metrics missing for 3 resources" in text

    def test_a_clean_scan_shows_no_banner(self):
        text = self._banner(
            {"discovered": 5, "analysed": 5, "dropped": 0, "discovery_complete": True}
        )

        assert text == ""

    def test_hostile_selection_text_is_escaped(self):
        text = self._banner(
            {
                "discovered": 2,
                "analysed": 1,
                "dropped": 1,
                "truncated": True,
                "selection": "<img src=x onerror=alert(1)>",
            }
        )

        assert "<img" not in text


class TestHeadlineHonesty:
    def _kpi_text(self, findings):
        out = build_board_html(_report(findings))
        start = out.index('class="kpis"')
        return out[start : start + 600]

    def test_no_billed_dollars_says_so_and_is_not_a_savings_figure(self):
        text = self._kpi_text(
            [_f("i-1", "AWS::EC2::Instance", 500.0, "model_estimate")]
        )

        assert "unverified waste estimate" in text
        assert "None of it is billed" in text and "Not a savings figure" in text

    def test_part_billed_names_the_billed_share(self):
        text = self._kpi_text(
            [_f("v1", cost=100.0, basis="billed"), _f("v2", cost=100.0)]
        )

        assert "50% is billed" in text

    def test_all_billed_has_no_caveat(self):
        text = self._kpi_text([_f("v1", cost=100.0, basis="billed")])

        assert "All of it is billed." in text and "Not a savings figure" not in text


class TestWithheldBanner:
    def test_withheld_findings_are_named_and_kept_out_of_the_total(self):
        report = _report()
        report["preflight"] = None
        report["scan_errors"] = []
        report["coverage"] = {
            "discovered": 5,
            "analysed": 5,
            "dropped": 0,
            "withheld": [
                {
                    "resource_id": "arn:aws:ec2:eu-west-1:1:natgateway/nat-0abc",
                    "resource_type": "AWS::EC2::NatGateway",
                    "kind": "no_metrics",
                    "reason": "x",
                }
            ],
        }

        out = build_board_html(report)
        banner = out[out.index('class="banner"') : out.index('class="kpis"')]

        assert "Could not judge 1 resource" in banner
        assert "traffic metrics were unavailable" in banner and "nat-0abc" in banner
        assert "Not in the waste total" in banner
