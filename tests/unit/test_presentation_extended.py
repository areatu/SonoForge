"""Extended unit tests for presentation layer widgets."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.gui


# ── dark_theme ─────────────────────────────────────────────────────


class TestDarkTheme:
    def test_get_theme_palette_dark(self) -> None:
        from echo_personal_tool.presentation.dark_theme import get_theme_palette

        with patch("echo_personal_tool.presentation.dark_theme.QApplication") as mock_app:
            mock_instance = MagicMock()
            mock_instance.palette.return_value.color.return_value.lightness.return_value = 50
            mock_app.instance.return_value = mock_instance
            palette = get_theme_palette()
            assert isinstance(palette, dict)
            assert "bg_dark" in palette

    def test_dark_palette_has_required_keys(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _DARK

        required = ["bg_dark", "bg_panel", "text", "accent", "border"]
        for key in required:
            assert key in _DARK, f"Missing key: {key}"

    def test_light_palette_has_required_keys(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _LIGHT

        required = ["bg_dark", "bg_panel", "text", "accent", "border"]
        for key in required:
            assert key in _LIGHT, f"Missing key: {key}"


# ── activity_bar ───────────────────────────────────────────────────


class TestActivityBar:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        assert bar.objectName() == "activityBar"
        assert bar.width() == 96

    def test_has_buttons(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        assert "measures" in bar._buttons
        assert "controls" in bar._buttons

    def test_has_action_buttons(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        assert "caliper" in bar._action_buttons
        assert "lv2d" in bar._action_buttons

    def test_set_active(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        bar.set_active("measures")
        assert bar._buttons["measures"].isChecked()
        assert not bar._buttons["controls"].isChecked()

    def test_set_active_none(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        bar.set_active("measures")
        bar.set_active(None)
        assert not bar._buttons["measures"].isChecked()

    def test_tab_activated_signal(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        received = []
        bar.tab_activated.connect(lambda name: received.append(name))
        bar._buttons["measures"].setChecked(True)
        bar._on_click("measures")
        assert received == ["measures"]

    def test_tab_deactivated_signal(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        received = []
        bar.tab_deactivated.connect(lambda name: received.append(name))
        bar._on_click("measures")
        assert received == ["measures"]

    def test_action_requested_signal(self, qtbot) -> None:
        from echo_personal_tool.presentation.activity_bar import ActivityBar

        bar = ActivityBar()
        qtbot.addWidget(bar)
        received = []
        bar.action_requested.connect(lambda name: received.append(name))
        bar._action_buttons["caliper"].click()
        assert received == ["caliper"]


# ── mmode_caliper ──────────────────────────────────────────────────


class TestMModeCaliperTool:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool()
        qtbot.addWidget(tool)
        assert tool.measurements == []
        assert tool._active_mode is None

    def test_start_distance(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool()
        qtbot.addWidget(tool)
        tool.start_distance_caliper()
        assert tool._active_mode == "distance"

    def test_start_time(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool()
        qtbot.addWidget(tool)
        tool.start_time_caliper()
        assert tool._active_mode == "time"

    def test_click_without_active_mode(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool()
        qtbot.addWidget(tool)
        tool.on_click(10.0, 20.0)
        assert tool.measurements == []

    def test_two_clicks_creates_measurement(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool()
        qtbot.addWidget(tool)
        tool.start_distance_caliper()
        tool.on_click(10.0, 5.0)
        tool.on_click(10.0, 50.0)
        assert len(tool.measurements) == 1
        assert tool.measurements[0].kind == "distance"

    def test_distance_with_calibration(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool(depth_mm_per_pixel=0.5)
        qtbot.addWidget(tool)
        tool.start_distance_caliper()
        tool.on_click(10.0, 10.0)
        tool.on_click(10.0, 30.0)
        assert tool.measurements[0].value_mm == 10.0  # 20px * 0.5

    def test_time_with_calibration(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool(time_ms_per_pixel=2.0)
        qtbot.addWidget(tool)
        tool.start_time_caliper()
        tool.on_click(10.0, 5.0)
        tool.on_click(50.0, 5.0)
        assert tool.measurements[0].value_ms == 80.0  # 40px * 2.0

    def test_clear(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_caliper import MModeCaliperTool

        tool = MModeCaliperTool()
        qtbot.addWidget(tool)
        tool.start_distance_caliper()
        tool.on_click(10.0, 5.0)
        tool.clear()
        assert tool.measurements == []
        assert tool._active_mode is None
        assert tool._first_click is None


# ── pyqtgraph_export ───────────────────────────────────────────────


class TestPyqtgraphExport:
    def test_allowed_exporter_classes_non_plot(self) -> None:
        from echo_personal_tool.presentation.pyqtgraph_export import (
            _PLOT_ONLY_EXPORTERS,
            allowed_exporter_classes,
        )

        result = allowed_exporter_classes("not_a_plot")
        for exporter in _PLOT_ONLY_EXPORTERS:
            assert exporter not in result


# ── segment_quality_panel ──────────────────────────────────────────


class TestSegmentQualityPanel:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.segment_quality_panel import (
            SegmentQualityPanel,
        )

        panel = SegmentQualityPanel()
        qtbot.addWidget(panel)
        assert panel._table.rowCount() > 0
        assert panel._table.columnCount() == 3

    def test_update_results(self, qtbot) -> None:
        from echo_personal_tool.presentation.segment_quality_panel import (
            SegmentQualityPanel,
        )

        panel = SegmentQualityPanel()
        qtbot.addWidget(panel)
        strain = {1: -20.0, 2: -18.0}
        quality = {1: 0.9, 2: 0.3}
        panel.update_results(strain, quality)
        # Should not crash
        assert panel._table.item(0, 1) is not None

    def test_low_quality_highlighting(self, qtbot) -> None:
        from echo_personal_tool.presentation.segment_quality_panel import (
            SegmentQualityPanel,
        )

        panel = SegmentQualityPanel()
        qtbot.addWidget(panel)
        quality = {1: 0.1}  # very low quality
        panel.update_results({}, quality)
        # Check that low quality items have special background
        for row in range(panel._table.rowCount()):
            item = panel._table.item(row, 2)
            if item is not None and item.text() == "0.1":
                assert item.background().color() == panel._LOW_QUALITY_BG


# ── properties_panel ───────────────────────────────────────────────


class TestPropertiesPanel:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        assert panel._instance_group.isHidden()
        assert panel._measurement_group.isHidden()
        assert panel._contour_group.isHidden()

    def test_update_instance_info(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.update_instance_info(modality="US", series_desc="A4C")
        assert not panel._instance_group.isHidden()
        assert panel._instance_form.rowCount() > 0

    def test_update_instance_empty(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.update_instance_info()
        assert panel._instance_group.isHidden()

    def test_update_measurement_info(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.update_measurement_info(label="IVSd", value_mm=9.5)
        assert not panel._measurement_group.isHidden()

    def test_update_measurement_empty(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.update_measurement_info()
        assert panel._measurement_group.isHidden()

    def test_update_contour_info(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.update_contour_info(chamber="LV", phase="ED", point_count=32)
        assert not panel._contour_group.isHidden()

    def test_update_contour_empty(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.update_contour_info()
        assert panel._contour_group.isHidden()

    def test_clear_all(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.update_instance_info(modality="US")
        panel.update_measurement_info(label="test")
        panel.update_contour_info(chamber="LV")
        panel.clear_all()
        assert panel._instance_group.isHidden()
        assert panel._measurement_group.isHidden()
        assert panel._contour_group.isHidden()

    def test_bmi_calculation(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_instance_info(
            modality="US",
            patient_height_m=1.80,
            patient_weight_kg=72.0,
        )
        # Instance group should be visible with height/weight/BMI
        assert not panel._instance_group.isHidden()
        assert panel._instance_form.rowCount() >= 3  # height, weight, BMI

    def test_update_instance_all_fields(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_instance_info(
            modality="US",
            series_desc="A4C Cine",
            frame_rate=30.0,
            pixel_spacing="0.5 x 0.5 mm",
            number_of_frames=30,
            patient_height_m=1.75,
            patient_weight_kg=70.0,
            media_format="mp4",
            frame_time_ms=33.3,
        )
        assert not panel._instance_group.isHidden()
        # modality, format, series, frame_rate, frame_time, frames, spacing, height, weight, BMI = 10
        assert panel._instance_form.rowCount() >= 8

    def test_update_instance_dicom_hides_format(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_instance_info(modality="US", media_format="dicom")
        # Format row should NOT be added for dicom
        assert panel._instance_form.rowCount() == 1  # only modality

    def test_update_instance_zero_frame_rate_hidden(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_instance_info(modality="US", frame_rate=0.0)
        assert panel._instance_form.rowCount() == 1  # only modality

    def test_update_instance_single_frame_hidden(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_instance_info(modality="US", number_of_frames=1)
        assert panel._instance_form.rowCount() == 1  # only modality

    def test_update_measurement_with_points(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_measurement_info(
            label="IVSd",
            value_mm=9.5,
            start=(10.0, 20.0),
            end=(10.0, 50.0),
        )
        assert not panel._measurement_group.isHidden()
        # label + value + pixel_length = 3 rows
        assert panel._measurement_form.rowCount() == 3

    def test_update_measurement_label_only(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_measurement_info(label="IVSd")
        assert panel._measurement_form.rowCount() == 1

    def test_update_contour_with_area(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_contour_info(
            chamber="LV",
            phase="ED",
            point_count=32,
            area_px=1500.0,
        )
        assert not panel._contour_group.isHidden()
        # chamber + phase + points + area = 4 rows
        assert panel._contour_form.rowCount() == 4

    def test_update_contour_chamber_only(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_contour_info(chamber="LV")
        assert panel._contour_form.rowCount() == 1

    def test_clear_form_removes_rows(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_instance_info(modality="US", series_desc="A4C")
        assert panel._instance_form.rowCount() >= 2
        # Update again - should clear first
        panel.update_instance_info(modality="CT")
        assert panel._instance_form.rowCount() == 1

    def test_zero_height_weight_no_bmi(self, qtbot) -> None:
        from echo_personal_tool.presentation.properties_panel import PropertiesPanel

        panel = PropertiesPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.update_instance_info(
            modality="US",
            patient_height_m=0.0,
            patient_weight_kg=0.0,
        )
        # No BMI row when height/weight are 0
        assert panel._instance_form.rowCount() == 1  # only modality


# ── measurement_results_dialog ─────────────────────────────────────


class TestMeasurementResultsDialog:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        snapshot = MeasurementSnapshot()
        dialog = MeasurementResultsDialog(snapshot)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() != ""
        assert dialog._text.isReadOnly()

    def test_empty_snapshot(self, qtbot) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(MeasurementSnapshot())
        qtbot.addWidget(dialog)
        text = dialog._text.toPlainText()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_none_snapshot(self, qtbot) -> None:
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(None)
        qtbot.addWidget(dialog)
        text = dialog._text.toPlainText()
        assert isinstance(text, str)

    def test_custom_pdf_name(self, qtbot) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(
            MeasurementSnapshot(), default_pdf_name="custom_report.pdf",
        )
        qtbot.addWidget(dialog)
        assert dialog._default_pdf_name == "custom_report.pdf"

    def test_custom_font_size(self, qtbot) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(
            MeasurementSnapshot(), pdf_font_size=14,
        )
        qtbot.addWidget(dialog)
        assert dialog._pdf_font_size == 14

    def test_export_pdf_cancel(self, qtbot) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(MeasurementSnapshot())
        qtbot.addWidget(dialog)
        with patch(
            "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
            return_value=("", ""),
        ):
            dialog._export_pdf()  # should return early, no crash

    def test_export_pdf_adds_extension(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(MeasurementSnapshot())
        qtbot.addWidget(dialog)
        output = tmp_path / "report"
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(output), ""),
            ),
            patch(
                "echo_personal_tool.presentation.measurement_results_dialog.export_measurement_report_pdf",
            ) as mock_export,
            patch(
                "echo_personal_tool.presentation.measurement_results_dialog.QDesktopServices",
            ),
        ):
            dialog._export_pdf()
            # Should add .pdf extension
            call_args = mock_export.call_args
            assert str(output.with_suffix(".pdf")) in str(call_args)

    def test_export_pdf_success(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(MeasurementSnapshot())
        qtbot.addWidget(dialog)
        output = tmp_path / "report.pdf"
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(output), ""),
            ),
            patch(
                "echo_personal_tool.presentation.measurement_results_dialog.export_measurement_report_pdf",
            ),
            patch(
                "echo_personal_tool.presentation.measurement_results_dialog.QDesktopServices",
            ) as mock_desktop,
        ):
            dialog._export_pdf()
            mock_desktop.openUrl.assert_called_once()

    def test_export_pdf_error(self, qtbot, tmp_path) -> None:
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
        from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        dialog = MeasurementResultsDialog(MeasurementSnapshot())
        qtbot.addWidget(dialog)
        output = tmp_path / "report.pdf"
        with (
            patch(
                "echo_personal_tool.presentation.styled_dialogs.styled_save_file",
                return_value=(str(output), ""),
            ),
            patch(
                "echo_personal_tool.presentation.measurement_results_dialog.export_measurement_report_pdf",
                side_effect=PdfExportError("font error"),
            ),
            patch(
                "echo_personal_tool.presentation.measurement_results_dialog.QMessageBox",
            ) as mock_msgbox,
        ):
            dialog._export_pdf()
            mock_msgbox.warning.assert_called_once()

    def test_populated_snapshot(self, qtbot) -> None:
        from echo_personal_tool.domain.models.measurements import (
            DopplerResults,
            MeasurementSnapshot,
        )
        from echo_personal_tool.presentation.measurement_results_dialog import (
            MeasurementResultsDialog,
        )

        snapshot = MeasurementSnapshot(doppler=DopplerResults(e_cm_s=85.0, a_cm_s=60.0))
        dialog = MeasurementResultsDialog(snapshot)
        qtbot.addWidget(dialog)
        text = dialog._text.toPlainText()
        assert "85.0" in text or "E" in text
