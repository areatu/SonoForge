"""The growth-chart plumbing (plan А.12, issue #650): header input, button, chart.

The fetal Z-scores need a gestational age the physician types into the report
header (the BP-field pattern); the chart button appears on the sheet exactly
when the document carries Z-score rows, and the chart itself reads the
document — no snapshot plumbing, no invented axis.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.services.report_builder import build_report_document
from echo_personal_tool.domain.services.report_document import PatientInfo, ReportDocument

PEDIATRIC_PROFILE = "builtin.pediatric_echo"
FETAL_PROFILE = "builtin.fetal_echo"


@pytest.fixture(scope="session", autouse=True)
def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _paediatric_document(*, research=False):
    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=34.0, millimeter_length=34.0),),
    )
    return build_report_document(snapshot, PatientInfo(bsa_m2=1.0), study_profile_id=PEDIATRIC_PROFILE)


class TestPatientHeaderGestationalAge:
    def test_the_header_editor_has_a_weeks_field(self) -> None:
        from echo_personal_tool.presentation.report_mode.patient import ReportPatientEditor

        editor = ReportPatientEditor(lambda key: key)
        assert "gestational_weeks" in editor._fields
        assert editor._fields["gestational_weeks"].placeholderText() == "report.gestational_age_hint"

    def test_the_ga_field_reports_its_edit(self) -> None:
        from echo_personal_tool.presentation.report_mode.patient import ReportPatientEditor

        editor = ReportPatientEditor(lambda key: key)
        seen: list[tuple[str, str]] = []
        editor.field_changed.connect(lambda name, text: seen.append((name, text)))
        editor._fields["gestational_weeks"].insert("32")  # insert() emits textEdited, setText() does not
        assert ("gestational_weeks", "32") in seen

    def test_the_coordinator_parser_accepts_weeks_and_refuses_junk(self) -> None:
        from echo_personal_tool.presentation.coordinators.report_coordinator import _parse_weeks

        assert _parse_weeks("32") == 32.0
        assert _parse_weeks("31,5") == 31.5
        assert _parse_weeks("") is None
        assert _parse_weeks("junk") is None
        assert _parse_weeks("99") is None  # beyond the plausible range


class TestGrowthChartEntries:
    def test_entries_come_from_the_document_z_rows(self) -> None:
        from echo_personal_tool.domain.services.pediatric_norms import cached_norms
        from echo_personal_tool.ui.growth_chart_widget import _chart_entries

        entries = _chart_entries(_paediatric_document(research=True), cached_norms())
        assert [entry.parameter_id for entry in entries] == ["lv.lvedd"]
        assert entries[0].z == pytest.approx(0.0)
        assert entries[0].axis == pytest.approx(1.0)

    def test_a_document_without_z_rows_has_no_entries(self) -> None:
        from echo_personal_tool.domain.services.pediatric_norms import cached_norms
        from echo_personal_tool.ui.growth_chart_widget import _chart_entries

        snapshot = MeasurementSnapshot(
            spacing_calibrated=True,
            linear_measurements=(LinearMeasurement(label="LVEDD", pixel_length=34.0, millimeter_length=34.0),),
        )
        document = build_report_document(snapshot, PatientInfo(bsa_m2=1.0), study_profile_id="builtin.adult_echo")
        assert _chart_entries(document, cached_norms()) == []

    def test_the_dialog_refuses_to_open_without_rows(self, _qapp) -> None:
        from echo_personal_tool.domain.services.report_document import ReportDocument
        from echo_personal_tool.ui.growth_chart_widget import show_growth_chart_dialog

        assert show_growth_chart_dialog(ReportDocument()) is False

    def test_the_dialog_draws_the_paediatric_sheet(self, _qapp, monkeypatch) -> None:
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.ui.growth_chart_widget import show_growth_chart_dialog

        opened: list = []

        class _Dialog(QDialog):
            def __init__(self, parent=None) -> None:
                super().__init__(parent)
                opened.append(self)

            def exec(self) -> None:
                pass  # no modal loop in tests

        monkeypatch.setattr("echo_personal_tool.ui.growth_chart_widget.QDialog", _Dialog)
        assert show_growth_chart_dialog(_paediatric_document(research=True)) is True
        assert opened


class TestSheetButton:
    def test_the_button_appearances_follow_the_document(self, _qapp) -> None:
        from echo_personal_tool.presentation.report_mode.preview import ReportPreview, _document_has_growth_rows

        preview = ReportPreview()
        assert preview._growth_button.isVisibleTo(preview) is False
        document = _paediatric_document()
        assert _document_has_growth_rows(document) is True
        assert _document_has_growth_rows(ReportDocument()) is False
        preview.set_document(document)
        assert preview._growth_button.isVisibleTo(preview) is True
