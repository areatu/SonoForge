"""Tests for exporters/pdf_exporter.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echo_personal_tool.constructor.exporters.pdf_exporter import (
    _build_html,
    _format_norm,
    export_to_pdf,
)
from echo_personal_tool.constructor.models import (
    NormRangeModel,
    ParameterModel,
    PathologyModel,
    ReferenceModel,
    TopicModel,
)


@pytest.fixture
def sample_model() -> ReferenceModel:
    return ReferenceModel(
        topics=[
            TopicModel(
                name="Левый желудочек",
                slug="lv",
                pathologies=[
                    PathologyModel(
                        name="Диастолическая",
                        slug="lv_diag",
                        description="Описание",
                        parameters=[
                            ParameterModel(
                                id="ea_ratio",
                                name="E/A ratio",
                                unit="",
                                norm_male=NormRangeModel(low=0.8, high=2.0),
                                pathology_desc="Снижение",
                            )
                        ],
                    )
                ],
            )
        ]
    )


class TestFormatNorm:
    def test_none(self) -> None:
        assert _format_norm(None) == "\u2014"

    def test_both(self) -> None:
        result = _format_norm(NormRangeModel(low=1.0, high=5.0))
        assert ">=1.0" in result
        assert "<=5.0" in result

    def test_low_only(self) -> None:
        result = _format_norm(NormRangeModel(low=3.0))
        assert ">=3.0" in result

    def test_high_only(self) -> None:
        result = _format_norm(NormRangeModel(high=10.0))
        assert "<=10.0" in result

    def test_empty_range(self) -> None:
        assert _format_norm(NormRangeModel()) == "\u2014"


class TestBuildHtml:
    def test_basic_structure(self, sample_model: ReferenceModel) -> None:
        html = _build_html(sample_model)
        assert "<html>" in html
        assert "</html>" in html
        assert "Левый желудочек" in html
        assert "ea_ratio" in html

    def test_pathology_description(self, sample_model: ReferenceModel) -> None:
        html = _build_html(sample_model)
        assert "Описание" in html

    def test_param_table(self, sample_model: ReferenceModel) -> None:
        html = _build_html(sample_model)
        assert "<table>" in html
        assert "E/A ratio" in html

    def test_empty_model(self) -> None:
        html = _build_html(ReferenceModel())
        assert "<html>" in html
        assert "</html>" in html

    def test_css_styles_present(self, sample_model: ReferenceModel) -> None:
        html = _build_html(sample_model)
        assert "<style>" in html
        assert "</style>" in html


class TestExportToPdf:
    def test_export_creates_pdf(self, sample_model: ReferenceModel, tmp_path: Path) -> None:
        out = tmp_path / "out.pdf"
        mock_printer = MagicMock()
        mock_doc = MagicMock()

        mock_margins = MagicMock()
        mock_page_layout_cls = MagicMock()
        mock_page_size_cls = MagicMock()
        mock_printer_cls = MagicMock(return_value=mock_printer)
        mock_doc_cls = MagicMock(return_value=mock_doc)

        mock_qt_core = MagicMock()
        mock_qt_core.QMarginsF = mock_margins
        mock_qt_core.QPageLayout = mock_page_layout_cls
        mock_qt_core.QPageSize = mock_page_size_cls

        mock_qt_gui = MagicMock()
        mock_qt_gui.QTextDocument = mock_doc_cls

        mock_qt_print = MagicMock()
        mock_qt_print.QPrinter = mock_printer_cls
        mock_qt_print.QPrinter.OutputFormat.PdfOutput = "PdfOutput"
        mock_printer_cls.OutputFormat.PdfOutput = "PdfOutput"

        import sys

        new_modules = {
            "PySide6.QtCore": mock_qt_core,
            "PySide6.QtGui": mock_qt_gui,
            "PySide6.QtPrintSupport": mock_qt_print,
        }

        # Save originals
        originals = {}
        for mod in new_modules:
            originals[mod] = sys.modules.get(mod)

        sys.modules.update(new_modules)

        try:
            export_to_pdf(sample_model, out)

            mock_printer.setOutputFileName.assert_called_once_with(str(out))
            mock_doc.setHtml.assert_called_once()
            mock_doc.print_.assert_called_once_with(mock_printer)
        finally:
            for mod, orig in originals.items():
                if orig is None:
                    sys.modules.pop(mod, None)
                else:
                    sys.modules[mod] = orig
