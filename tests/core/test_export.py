from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.reports.export import export_pdf, export_pptx, get_report_formats


def _fake_report() -> dict:
    return {
        "schema_version": "1.0",
        "scan_id": "test-scan-id",
        "generated_at": "2026-06-19T00:00:00+00:00",
        "cloud": "aws",
        "accounts_scanned": ["123456789012"],
        "total_estimated_waste_usd": 500.0,
        "findings_count": 2,
        "findings": [
            {
                "resource_id": "i-abc",
                "resource_type": "EC2",
                "name": "web-server-1",
                "estimated_monthly_cost": 300.0,
                "priority": "high",
                "waste_reason": "idle",
                "recommendation": "terminate",
            },
            {
                "resource_id": "i-def",
                "resource_type": "RDS",
                "name": None,
                "estimated_monthly_cost": 200.0,
                "priority": "medium",
                "waste_reason": "low connections",
                "recommendation": "downsize",
            },
        ],
        "executive_summary": "Two idle resources found.",
        "agent_input_tokens": 5000,
        "agent_output_tokens": 1500,
        "estimated_agent_cost_usd": 0.0375,
    }


class TestGetReportFormats:
    def test_default_is_json_html(self, monkeypatch):
        monkeypatch.delenv("REPORT_FORMAT", raising=False)
        assert get_report_formats() == {"json", "html"}

    def test_custom_formats(self, monkeypatch):
        monkeypatch.setenv("REPORT_FORMAT", "json,pdf,pptx")
        assert get_report_formats() == {"json", "pdf", "pptx"}

    def test_whitespace_handling(self, monkeypatch):
        monkeypatch.setenv("REPORT_FORMAT", " pdf , json ")
        assert get_report_formats() == {"pdf", "json"}

    def test_single_format(self, monkeypatch):
        monkeypatch.setenv("REPORT_FORMAT", "json")
        assert get_report_formats() == {"json"}


class TestExportPdf:
    def test_raises_without_weasyprint(self):
        with patch.dict("sys.modules", {"weasyprint": None}):
            with pytest.raises(ImportError, match="weasyprint"):
                export_pdf(_fake_report(), Path("/tmp/test"))

    def test_calls_weasyprint(self, tmp_path):
        mock_html_cls = MagicMock()
        mock_weasyprint = MagicMock()
        mock_weasyprint.HTML = mock_html_cls

        with patch.dict("sys.modules", {"weasyprint": mock_weasyprint}):
            result = export_pdf(_fake_report(), tmp_path / "report")

        assert str(result).endswith(".pdf")
        mock_html_cls.assert_called_once()
        mock_html_cls.return_value.write_pdf.assert_called_once()


class TestExportPptx:
    def test_raises_without_python_pptx(self):
        with patch.dict("sys.modules", {"pptx": None, "pptx.util": None}):
            with pytest.raises(ImportError, match="python-pptx"):
                export_pptx(_fake_report(), Path("/tmp/test"))

    def test_creates_pptx_file(self, tmp_path):
        pytest.importorskip("pptx")
        output = tmp_path / "report"
        result = export_pptx(_fake_report(), output)
        assert result.exists()
        assert result.suffix == ".pptx"

    def test_pptx_has_slides(self, tmp_path):
        pytest.importorskip("pptx")
        output = tmp_path / "report"
        export_pptx(_fake_report(), output)
        from pptx import Presentation

        prs = Presentation(str(output.with_suffix(".pptx")))
        assert len(prs.slides) >= 3


class TestSaveReportsLocally:
    def test_respects_report_format_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORT_FORMAT", "json")
        monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path))

        from core.reports.delivery import save_reports_locally

        save_reports_locally(_fake_report())

        json_files = list(tmp_path.rglob("*.json"))
        html_files = list(tmp_path.rglob("*.html"))
        assert len(json_files) == 1
        assert len(html_files) == 0

    def test_pdf_skipped_gracefully_when_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPORT_FORMAT", "json,pdf")
        monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path))

        with patch(
            "core.reports.export.export_pdf",
            side_effect=ImportError("weasyprint not installed"),
        ):
            from core.reports.delivery import save_reports_locally

            save_reports_locally(_fake_report())

        json_files = list(tmp_path.rglob("*.json"))
        assert len(json_files) == 1
