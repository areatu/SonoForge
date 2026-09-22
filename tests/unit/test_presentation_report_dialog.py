"""Unit tests for presentation/report_dialog.py (the study report window)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    DopplerResults,
    IndexedMeasurements,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.services.report_builder import PatientInfo
from echo_personal_tool.infrastructure.i18n import tr

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _snapshot() -> MeasurementSnapshot:
    return MeasurementSnapshot(
        doppler=DopplerResults(e_cm_s=95.0, a_cm_s=60.0, ivrt_ms=95.0),
        lvef=LvefResult(
            a4c=LvViewMetrics(length_ed_mm=85.0, edv_ml=120.0, esv_ml=45.0),
            lvef_percent=48.0,
        ),
        indexed=IndexedMeasurements(bsa_m2=1.9, lvmi_g_m2=126.0),
        linear_measurements=(
            LinearMeasurement(label="LVEDD", pixel_length=120, millimeter_length=62.0),
        ),
    )


class TestConstruction:
    def test_creates_with_snapshot(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot())
        assert dialog.windowTitle() == tr("report.title")
        assert dialog._tree.topLevelItemCount() > 0

    def test_none_snapshot_is_allowed(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(None)
        assert dialog._tree.topLevelItemCount() == 0
        assert dialog.document().has_measurements is False

    def test_custom_pdf_name_and_font_size(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot(), default_pdf_name="study.pdf", pdf_font_size=14)
        assert dialog._default_pdf_name == "study.pdf"
        assert dialog._pdf_font_size == 14

    def test_header_is_prefilled_from_dicom(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(
            _snapshot(),
            patient=PatientInfo(name="Иванов И.И.", patient_id="12345", sex="F"),
        )
        assert dialog._fields["name"].text() == "Иванов И.И."
        assert dialog._fields["patient_id"].text() == "12345"
        assert dialog._sex.currentData() == "F"


class TestGroupedTable:
    def test_rows_are_grouped_by_anatomy(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot())
        titles = [
            dialog._tree.topLevelItem(i).text(0)
            for i in range(dialog._tree.topLevelItemCount())
        ]
        assert tr("report.group.lv") in titles
        assert tr("report.group.mv") in titles

    def test_value_row_shows_value_unit_and_norm(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot(), patient=PatientInfo(sex="M"))
        lvedd = None
        for i in range(dialog._tree.topLevelItemCount()):
            top = dialog._tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.text(0) == "LVEDD":
                    lvedd = child
        assert lvedd is not None
        assert lvedd.text(1) == "62.0"
        assert lvedd.text(2) == "mm"
        assert lvedd.text(3) == "42–59"

    def test_pathological_row_is_highlighted(self) -> None:
        from echo_personal_tool.presentation.report_dialog import _PATHOLOGY_COLOR, ReportDialog

        dialog = ReportDialog(_snapshot(), patient=PatientInfo(sex="M"))
        colors = set()
        for i in range(dialog._tree.topLevelItemCount()):
            top = dialog._tree.topLevelItem(i)
            for j in range(top.childCount()):
                colors.add(top.child(j).foreground(1).color().name())
        assert _PATHOLOGY_COLOR.name() in colors

    def test_changing_sex_rebuilds_the_norms(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot(), patient=PatientInfo(sex="M"))
        male = [v.norm for v in dialog.document().pathological_values if v.label == "LVEDD"]
        dialog._sex.setCurrentIndex(2)  # female
        female = [v.norm for v in dialog.document().pathological_values if v.label == "LVEDD"]
        assert male == ["42–59"]
        assert female == ["36–51"]

    def test_conclusion_is_part_of_the_document(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot())
        dialog._conclusion.setPlainText("Дилатация ЛП.")
        assert dialog.document().patient.conclusion == "Дилатация ЛП."


class TestExportPdf:
    def test_cancel_does_nothing(self) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot())
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=("", ""),
            ),
            patch(
                "echo_personal_tool.presentation.report_dialog.export_report_document_pdf"
            ) as mock_export,
        ):
            dialog._export_pdf()
            mock_export.assert_not_called()

    def test_appends_pdf_extension(self, tmp_path) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot())
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(tmp_path / "report"), ""),
            ),
            patch(
                "echo_personal_tool.presentation.report_dialog.export_report_document_pdf"
            ) as mock_export,
            patch("echo_personal_tool.presentation.report_dialog.QDesktopServices"),
        ):
            dialog._export_pdf()
            assert str(mock_export.call_args[0][1]).endswith(".pdf")

    def test_opens_the_result(self, tmp_path) -> None:
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot())
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(tmp_path / "report.pdf"), ""),
            ),
            patch("echo_personal_tool.presentation.report_dialog.export_report_document_pdf"),
            patch(
                "echo_personal_tool.presentation.report_dialog.QDesktopServices"
            ) as mock_desktop,
        ):
            dialog._export_pdf()
            mock_desktop.openUrl.assert_called_once()

    def test_warns_on_export_error(self, tmp_path) -> None:
        from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError
        from echo_personal_tool.presentation.report_dialog import ReportDialog

        dialog = ReportDialog(_snapshot())
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(tmp_path / "report.pdf"), ""),
            ),
            patch(
                "echo_personal_tool.presentation.report_dialog.export_report_document_pdf",
                side_effect=PdfExportError("font error"),
            ),
            patch(
                "echo_personal_tool.presentation.report_dialog.QMessageBox"
            ) as mock_msgbox,
        ):
            dialog._export_pdf()
            mock_msgbox.warning.assert_called_once()
