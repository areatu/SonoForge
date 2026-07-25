"""Unit tests for presentation/measurement_results_dialog.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestMeasurementResultsDialogConstruction:
    @patch("echo_personal_tool.presentation.measurement_results_dialog.format_measurement_report", return_value="Test Report")
    def test_creates_with_report(self, mock_format):
        from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog

        dlg = MeasurementResultsDialog(snapshot=None)
        assert dlg.windowTitle() != ""
        assert dlg._report_text == "Test Report"
        assert dlg._text.toPlainText() == "Test Report"
        assert dlg._text.isReadOnly()

    @patch("echo_personal_tool.presentation.measurement_results_dialog.format_measurement_report", return_value="No data")
    def test_custom_font_size(self, mock_format):
        from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog

        dlg = MeasurementResultsDialog(snapshot=None, pdf_font_size=14)
        assert dlg._pdf_font_size == 14

    @patch("echo_personal_tool.presentation.measurement_results_dialog.format_measurement_report", return_value="Report")
    def test_custom_pdf_name(self, mock_format):
        from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog

        dlg = MeasurementResultsDialog(snapshot=None, default_pdf_name="custom.pdf")
        assert dlg._default_pdf_name == "custom.pdf"


class TestExportPdfSuccess:
    @patch("echo_personal_tool.presentation.measurement_results_dialog.QDesktopServices.openUrl")
    @patch("echo_personal_tool.presentation.measurement_results_dialog.export_measurement_report_pdf")
    @patch("echo_personal_tool.presentation.styled_dialogs.styled_save_file", return_value=("/tmp/report.pdf", "PDF"))
    @patch("echo_personal_tool.presentation.measurement_results_dialog.format_measurement_report", return_value="Report")
    def test_exports_pdf(self, mock_format, mock_save, mock_export, mock_open):
        from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog

        dlg = MeasurementResultsDialog(snapshot=None)
        dlg._export_pdf()
        mock_export.assert_called_once()
        mock_open.assert_called_once()

    @patch("echo_personal_tool.presentation.measurement_results_dialog.QDesktopServices.openUrl")
    @patch("echo_personal_tool.presentation.measurement_results_dialog.export_measurement_report_pdf")
    @patch("echo_personal_tool.presentation.styled_dialogs.styled_save_file", return_value=("/tmp/report", "PDF"))
    @patch("echo_personal_tool.presentation.measurement_results_dialog.format_measurement_report", return_value="Report")
    def test_appends_pdf_extension(self, mock_format, mock_save, mock_export, mock_open):
        from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog

        dlg = MeasurementResultsDialog(snapshot=None)
        dlg._export_pdf()
        call_args = mock_export.call_args
        output_path = call_args[0][1]
        assert str(output_path).endswith(".pdf")


class TestExportPdfCancelled:
    @patch("echo_personal_tool.presentation.styled_dialogs.styled_save_file", return_value=("", ""))
    @patch("echo_personal_tool.presentation.measurement_results_dialog.format_measurement_report", return_value="Report")
    def test_cancel_does_nothing(self, mock_format, mock_save):
        from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog

        dlg = MeasurementResultsDialog(snapshot=None)
        with patch("echo_personal_tool.presentation.measurement_results_dialog.export_measurement_report_pdf") as mock_export:
            dlg._export_pdf()
            mock_export.assert_not_called()


class TestExportPdfError:
    from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError

    @patch("echo_personal_tool.presentation.measurement_results_dialog.QMessageBox.warning")
    @patch(
        "echo_personal_tool.presentation.measurement_results_dialog.export_measurement_report_pdf",
        side_effect=PdfExportError("write failed"),
    )
    @patch("echo_personal_tool.presentation.styled_dialogs.styled_save_file", return_value=("/tmp/report.pdf", "PDF"))
    @patch("echo_personal_tool.presentation.measurement_results_dialog.format_measurement_report", return_value="Report")
    def test_shows_warning_on_error(self, mock_format, mock_save, mock_export, mock_warn):
        from echo_personal_tool.presentation.measurement_results_dialog import MeasurementResultsDialog

        dlg = MeasurementResultsDialog(snapshot=None)
        dlg._export_pdf()
        mock_warn.assert_called_once()
