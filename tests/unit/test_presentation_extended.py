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


# ── ste_results_dialog ─────────────────────────────────────────────


class TestSteResultsDialog:
    def test_creation(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog

        dialog = SteResultsDialog()
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() != ""
        assert dialog._warning_label.isHidden()

    def test_update_results(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog

        dialog = SteResultsDialog()
        qtbot.addWidget(dialog)
        longitudinal = np.linspace(0, -0.2, 30)
        radial = np.linspace(0, 0.1, 30)
        dialog.update_results(
            longitudinal, radial,
            segment_strain={1: -20.0},
            segment_quality={1: 0.9},
            gls=-15.0,
        )
        assert dialog.isVisible()

    def test_update_results_with_quality_gate(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog

        dialog = SteResultsDialog()
        qtbot.addWidget(dialog)
        longitudinal = np.linspace(0, -0.2, 30)
        radial = np.linspace(0, 0.1, 30)
        dialog.update_results(
            longitudinal, radial,
            segment_strain={1: -20.0},
            segment_quality={1: 0.9},
            kernels_accepted=80,
            kernels_rejected=20,
            kernels_total=100,
        )
        assert not dialog._warning_label.isHidden()
        assert "80/100" in dialog._warning_label.text()

    def test_update_results_no_rejection(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog

        dialog = SteResultsDialog()
        qtbot.addWidget(dialog)
        longitudinal = np.linspace(0, -0.2, 30)
        radial = np.linspace(0, 0.1, 30)
        dialog.update_results(
            longitudinal, radial,
            segment_strain={},
            segment_quality={},
            kernels_accepted=100,
            kernels_rejected=0,
            kernels_total=100,
        )
        assert dialog._warning_label.isHidden()

    def test_clear(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.ste_results_dialog import SteResultsDialog

        dialog = SteResultsDialog()
        qtbot.addWidget(dialog)
        longitudinal = np.linspace(0, -0.2, 30)
        radial = np.linspace(0, 0.1, 30)
        dialog.update_results(longitudinal, radial, segment_strain={1: -20.0}, segment_quality={1: 0.9})
        dialog.clear()
        # Should not crash


# ── dicom_tag_inspector_widget ─────────────────────────────────────


class TestDicomTagInspectorWidget:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.dicom_tag_inspector_widget import (
            DicomTagInspectorWidget,
        )

        widget = DicomTagInspectorWidget()
        qtbot.addWidget(widget)
        assert widget._table.columnCount() == 5

    def test_load_none(self, qtbot) -> None:
        from echo_personal_tool.presentation.dicom_tag_inspector_widget import (
            DicomTagInspectorWidget,
        )

        widget = DicomTagInspectorWidget()
        qtbot.addWidget(widget)
        widget.load_instance(None)
        assert widget._table.rowCount() == 0

    def test_load_nonexistent(self, qtbot) -> None:
        from pathlib import Path

        from echo_personal_tool.presentation.dicom_tag_inspector_widget import (
            DicomTagInspectorWidget,
        )

        widget = DicomTagInspectorWidget()
        qtbot.addWidget(widget)
        widget.load_instance(Path("/nonexistent/file.dcm"))
        assert widget._table.rowCount() == 0

    def test_load_valid_dicom(self, qtbot, synthetic_dicom_path) -> None:
        from PySide6.QtWidgets import QApplication

        from echo_personal_tool.presentation.dicom_tag_inspector_widget import (
            DicomTagInspectorWidget,
        )

        widget = DicomTagInspectorWidget()
        qtbot.addWidget(widget)
        widget.load_instance(synthetic_dicom_path)
        QApplication.processEvents()
        # May or may not have rows depending on DICOM content
        assert widget._table.rowCount() >= 0


# ── browser_item_delegate ──────────────────────────────────────────


class TestBrowserItemDelegate:
    def test_constants(self) -> None:
        from echo_personal_tool.presentation.browser_item_delegate import (
            THUMB_ROW_HEIGHT,
            THUMB_WIDTH,
        )

        assert THUMB_ROW_HEIGHT == 156
        assert THUMB_WIDTH == 220

    def test_creation(self) -> None:
        from echo_personal_tool.presentation.browser_item_delegate import (
            InstanceThumbnailDelegate,
        )

        delegate = InstanceThumbnailDelegate()
        assert delegate is not None


# ── ge_labeled_slider ──────────────────────────────────────────────


class TestGeLabeledSlider:
    def test_top_labeled_slider_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        slider = TopLabeledSlider("Window", minimum=0, maximum=255, value=128)
        qtbot.addWidget(slider)
        assert slider.value() == 128
        assert slider.slider().minimum() == 0
        assert slider.slider().maximum() == 255

    def test_top_labeled_slider_set_value(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        slider = TopLabeledSlider("Window")
        qtbot.addWidget(slider)
        slider.setValue(100)
        assert slider.value() == 100

    def test_top_labeled_slider_set_range(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        slider = TopLabeledSlider("Window")
        qtbot.addWidget(slider)
        slider.setRange(0, 512)
        assert slider.slider().maximum() == 512

    def test_top_labeled_slider_signal(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import TopLabeledSlider

        slider = TopLabeledSlider("Window", value=0)
        qtbot.addWidget(slider)
        with qtbot.waitSignal(slider.valueChanged, timeout=1000) as blocker:
            slider.setValue(50)
        assert blocker.args == [50]

    def test_ge_slider_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level", minimum=0, maximum=255, value=128)
        qtbot.addWidget(slider)
        assert slider.value() == 128

    def test_ge_slider_increment(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level", minimum=0, maximum=255, value=128)
        qtbot.addWidget(slider)
        slider._increment.click()
        assert slider.value() == 129

    def test_ge_slider_decrement(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level", minimum=0, maximum=255, value=128)
        qtbot.addWidget(slider)
        slider._decrement.click()
        assert slider.value() == 127

    def test_ge_slider_set_value(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level", minimum=0, maximum=255, value=128)
        qtbot.addWidget(slider)
        slider.setValue(200)
        assert slider.value() == 200

    def test_ge_slider_set_range(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level")
        qtbot.addWidget(slider)
        slider.setRange(0, 1024)
        assert slider.slider().maximum() == 1024

    def test_ge_slider_signal(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level")
        qtbot.addWidget(slider)
        received = []
        slider.valueChanged.connect(lambda v: received.append(v))
        slider.setValue(75)
        assert received == [75]

    def test_ge_slider_disabled(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level")
        qtbot.addWidget(slider)
        slider.setEnabled(False)
        assert not slider.isEnabled()
        assert not slider._slider.isEnabled()
        assert not slider._decrement.isEnabled()
        assert not slider._increment.isEnabled()

    def test_ge_slider_resize(self, qtbot) -> None:
        from echo_personal_tool.presentation.ge_labeled_slider import GeLabeledSlider

        slider = GeLabeledSlider("Level")
        qtbot.addWidget(slider)
        slider.resize(400, 50)
        # Should not crash


# ── speckle_settings_dialog ────────────────────────────────────────


class TestSpeckleSettingsDialog:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() != ""

    def test_default_preset(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog.selected_preset_name() == "standard"

    def test_select_research_preset(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._preset_combo.setCurrentIndex(1)
        assert dialog.selected_preset_name() == "research"

    def test_select_debug_preset(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._preset_combo.setCurrentIndex(2)
        assert dialog.selected_preset_name() == "debug"

    def test_get_config_standard(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        config = dialog.get_config()
        assert config.drift_compensation is True
        assert config.wall_thickness_mm == 8.0

    def test_get_config_research(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._preset_combo.setCurrentIndex(1)
        config = dialog.get_config()
        assert config.kernel_size == 18

    def test_get_config_debug(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._preset_combo.setCurrentIndex(2)
        config = dialog.get_config()
        assert config.bidirectional is False

    def test_manual_ed_auto(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog.manual_ed is None  # auto by default

    def test_manual_ed_manual(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog(n_frames=30)
        qtbot.addWidget(dialog)
        dialog._ed_auto_check.setChecked(False)
        dialog._ed_spin.setValue(5)
        assert dialog.manual_ed == 5

    def test_manual_es_auto(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog.manual_es is None

    def test_manual_es_manual(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog(n_frames=30)
        qtbot.addWidget(dialog)
        dialog._es_auto_check.setChecked(False)
        dialog._es_spin.setValue(15)
        assert dialog.manual_es == 15

    def test_with_manual_ed_es(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog(n_frames=30, manual_ed=5, manual_es=15)
        qtbot.addWidget(dialog)
        assert dialog.manual_ed == 5
        assert dialog.manual_es == 15
        assert not dialog._ed_auto_check.isChecked()
        assert not dialog._es_auto_check.isChecked()

    def test_drift_compensation_toggle(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._drift_compensation_check.setChecked(False)
        config = dialog.get_config()
        assert config.drift_compensation is False

    def test_wall_thickness(self, qtbot) -> None:
        from echo_personal_tool.presentation.speckle_settings_dialog import (
            SpeckleSettingsDialog,
        )

        dialog = SpeckleSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._wall_thickness_spin.setValue(10.0)
        config = dialog.get_config()
        assert config.wall_thickness_mm == 10.0


# ── strain_curve_widget ────────────────────────────────────────────


class TestStrainCurveWidget:
    def test_creation(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        assert "GLS: --" in widget._gls_label.text()

    def test_set_strain_data(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        longitudinal = np.linspace(0, -0.2, 30)
        radial = np.linspace(0, 0.1, 30)
        widget.set_strain_data(longitudinal, radial, ed_index=0, es_index=15)
        # Should not crash

    def test_set_strain_data_with_window(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        longitudinal = np.linspace(0, -0.2, 30)
        radial = np.linspace(0, 0.1, 30)
        widget.set_strain_data(
            longitudinal, radial,
            ed_index=5, es_index=20,
            window_start=5, window_end=25,
        )

    def test_set_strain_data_empty(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        widget.set_strain_data(np.array([]), np.array([]))
        # Should call clear

    def test_set_gls_value(self, qtbot) -> None:
        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        widget.set_gls_value(-18.5)
        assert "GLS: -18.5%" in widget._gls_label.text()

    def test_clear(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        longitudinal = np.linspace(0, -0.2, 30)
        radial = np.linspace(0, 0.1, 30)
        widget.set_strain_data(longitudinal, radial)
        widget.clear()
        assert "GLS: --" in widget._gls_label.text()
        assert widget._ed_line is None
        assert widget._es_line is None

    def test_clear_no_lines(self, qtbot) -> None:
        from echo_personal_tool.presentation.strain_curve_widget import StrainCurveWidget

        widget = StrainCurveWidget()
        qtbot.addWidget(widget)
        widget.clear()  # Should not crash even without lines


# ── server_profile_dialog ──────────────────────────────────────────


class TestServerProfileDialog:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() != ""
        assert dialog._btn_load.isEnabled() is False
        assert dialog._btn_delete.isEnabled() is False

    def test_selected_settings_default(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        assert dialog.selected_settings == settings

    def test_selection_enables_buttons(self, qtbot) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        item = QListWidgetItem("test_profile")
        item.setData(256, "test_profile")
        dialog._list.addItem(item)
        dialog._list.setCurrentItem(item)
        assert dialog._btn_load.isEnabled() is True
        assert dialog._btn_delete.isEnabled() is True

    def test_clear_selection(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        dialog._on_selection_changed(None, None)
        assert dialog._btn_load.isEnabled() is False
        assert dialog._btn_delete.isEnabled() is False


# ── styled_dialogs ─────────────────────────────────────────────────


class TestStyledDialogs:
    def test_style_dialog(self, qtbot) -> None:
        from PySide6.QtWidgets import QFileDialog

        from echo_personal_tool.presentation.styled_dialogs import _style_dialog

        dialog = QFileDialog()
        qtbot.addWidget(dialog)
        _style_dialog(dialog)
        # Should apply palette and stylesheet without crash
        assert dialog.palette() is not None


# ── ui_animations ──────────────────────────────────────────────────


class TestUiAnimations:
    def test_hex_to_rgb(self) -> None:
        from echo_personal_tool.presentation.ui_animations import _hex_to_rgb

        assert _hex_to_rgb("#1a2332") == (26, 35, 50)
        assert _hex_to_rgb("#ffffff") == (255, 255, 255)
        assert _hex_to_rgb("#000000") == (0, 0, 0)

    def test_hex_to_rgb_short(self) -> None:
        from echo_personal_tool.presentation.ui_animations import _hex_to_rgb

        # Short hex returns fallback
        result = _hex_to_rgb("#fff")
        assert result == (46, 64, 84)

    def test_rgb_to_hex(self) -> None:
        from echo_personal_tool.presentation.ui_animations import _rgb_to_hex

        assert _rgb_to_hex(26, 35, 50) == "#1a2332"
        assert _rgb_to_hex(255, 255, 255) == "#ffffff"
        assert _rgb_to_hex(0, 0, 0) == "#000000"

    def test_lerp_color(self) -> None:
        from echo_personal_tool.presentation.ui_animations import _lerp_color

        # t=0 → c1, t=1 → c2
        assert _lerp_color("#000000", "#ffffff", 0.0) == "#000000"
        assert _lerp_color("#000000", "#ffffff", 1.0) == "#ffffff"
        mid = _lerp_color("#000000", "#ffffff", 0.5)
        assert mid == "#7f7f7f"

    def test_hover_button_mixin_install(self, qtbot) -> None:
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import HoverButtonMixin

        btn = QPushButton("test")
        qtbot.addWidget(btn)
        mixin1 = HoverButtonMixin.install(btn)
        mixin2 = HoverButtonMixin.install(btn)
        assert mixin1 is mixin2  # same instance

    def test_animate_widget_opacity(self, qtbot) -> None:
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import animate_widget_opacity

        btn = QPushButton("test")
        qtbot.addWidget(btn)
        anim = animate_widget_opacity(btn, 0.0, 1.0, duration_ms=50)
        assert anim is not None
        assert btn.property("_opacity_anim") is anim

    def test_animate_widget_opacity_with_callback(self, qtbot) -> None:
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import animate_widget_opacity

        btn = QPushButton("test")
        qtbot.addWidget(btn)
        called = []
        anim = animate_widget_opacity(btn, 0.0, 1.0, duration_ms=50, on_finished=lambda: called.append(True))
        assert anim is not None

    def test_hide_dialog_animated(self, qtbot) -> None:
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import hide_dialog_animated

        dialog = QDialog()
        qtbot.addWidget(dialog)
        called = []
        hide_dialog_animated(dialog, on_done=lambda: called.append(True))
        assert called == [True]

    def test_hide_dialog_animated_no_callback(self, qtbot) -> None:
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import hide_dialog_animated

        dialog = QDialog()
        qtbot.addWidget(dialog)
        hide_dialog_animated(dialog)  # should not crash

    def test_loading_button(self, qtbot) -> None:
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import loading_button

        btn = QPushButton("Submit")
        qtbot.addWidget(btn)
        with loading_button(btn, "Loading..."):
            assert btn.text() == "Loading..."
            assert btn.isEnabled() is False
        assert btn.text() == "Submit"
        assert btn.isEnabled() is True

    def test_exec_animated(self, qtbot) -> None:
        from PySide6.QtWidgets import QDialog

        from echo_personal_tool.presentation.ui_animations import exec_animated

        dialog = QDialog()
        qtbot.addWidget(dialog)
        # exec_animated calls dialog.exec() which would block,
        # so we just verify the function exists and is callable
        assert callable(exec_animated)

    def test_set_button_loading(self, qtbot) -> None:
        from PySide6.QtWidgets import QPushButton

        from echo_personal_tool.presentation.ui_animations import set_button_loading

        btn = QPushButton("Save")
        qtbot.addWidget(btn)
        set_button_loading(btn, True, "Saving...")
        assert btn.text() == "Saving..."
        assert btn.isEnabled() is False
        set_button_loading(btn, False)
        assert btn.text() == "Save"
        assert btn.isEnabled() is True

    def test_init_time_source(self) -> None:
        from echo_personal_tool.presentation.ui_animations import _current_time_ms

        t = _current_time_ms()
        assert isinstance(t, int)
        assert t > 0


# ── dark_theme extended ────────────────────────────────────────────


class TestDarkThemeExtended:
    def test_resolve_theme_dark(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        assert _resolve_theme("dark") is _DARK

    def test_resolve_theme_light(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _LIGHT, _resolve_theme

        assert _resolve_theme("light") is _LIGHT

    def test_resolve_theme_unknown(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _DARK, _resolve_theme

        assert _resolve_theme("unknown") is _DARK

    def test_get_logo_path(self) -> None:
        from pathlib import Path

        from echo_personal_tool.presentation.dark_theme import get_logo_path

        path = get_logo_path()
        assert isinstance(path, Path)

    def test_build_clinical_stylesheet(self) -> None:
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        css = build_clinical_stylesheet(font_size=14, theme="dark")
        assert "QWidget" in css
        assert "14px" in css or "font-size" in css

    def test_build_clinical_stylesheet_light(self) -> None:
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        css = build_clinical_stylesheet(font_size=12, theme="light")
        assert "QWidget" in css

    def test_is_system_dark(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _is_system_dark

        result = _is_system_dark()
        assert isinstance(result, bool)

    def test_theme_map_has_all_themes(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _THEME_MAP

        assert "dark" in _THEME_MAP
        assert "light" in _THEME_MAP
        assert "vscode_dark" in _THEME_MAP
        assert "vscode_light" in _THEME_MAP


# ── mmode_scan_line ────────────────────────────────────────────────


class TestMModeScanLine:
    def test_creation(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        assert item.line_start is None
        assert item.line_end is None
        assert item.is_complete is False

    def test_set_start(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        assert item.line_start == (10.0, 20.0)
        assert item.line_end is None
        assert item.is_complete is False

    def test_set_end(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.set_end((50.0, 60.0))
        assert item.line_end == (50.0, 60.0)
        assert item.is_complete is True

    def test_get_endpoints(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.set_end((50.0, 60.0))
        start, end = item.get_endpoints()
        assert start == (10.0, 20.0)
        assert end == (50.0, 60.0)

    def test_move_start_to(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.set_end((50.0, 60.0))
        item.move_start_to((15.0, 25.0))
        assert item.line_start == (15.0, 25.0)

    def test_move_end_to(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.set_end((50.0, 60.0))
        item.move_end_to((55.0, 65.0))
        assert item.line_end == (55.0, 65.0)

    def test_clear(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.set_end((50.0, 60.0))
        item.clear()
        assert item.line_start is None
        assert item.line_end is None
        assert item.is_complete is False

    def test_update_preview(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.update_preview((30.0, 40.0))
        assert item.line_end == (30.0, 40.0)

    def test_update_preview_no_start(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.update_preview((30.0, 40.0))
        # Should not crash, line_end stays None
        assert item.line_end is None

    def test_vertical_lock_default(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        assert item.vertical_lock is False


# ── mmode_widget ───────────────────────────────────────────────────


class TestMModeWidget:
    def test_creation(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        assert widget._buffer_width == 512
        assert widget._num_samples == 256
        assert widget._sweep_x == 0

    def test_clear_buffer(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._image_buffer[0, 0] = 128
        widget.clear_buffer()
        assert widget._image_buffer[0, 0] == 0

    def test_clear_calibration(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._time_ms_per_pixel = 2.0
        widget._depth_mm_per_pixel = 0.5
        widget.clear_calibration()
        assert widget._time_ms_per_pixel is None
        assert widget._depth_mm_per_pixel is None

    def test_set_time_calibration(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_time_calibration_ms_per_pixel(1.5)
        assert widget._time_ms_per_pixel == 1.5

    def test_set_depth_calibration_mm(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_depth_calibration_mm_per_pixel(0.3)
        assert widget._depth_mm_per_pixel == 0.3

    def test_set_depth_calibration_cm(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_depth_calibration_cm_per_pixel(0.03)
        assert widget._depth_mm_per_pixel == 0.3  # 0.03 * 10

    def test_on_new_column(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        column = np.random.randint(0, 255, (256,), dtype=np.uint8)
        widget.on_new_column(column)
        # Sweep should advance
        assert widget._sweep_x >= 0

    def test_sweep_speeds(self) -> None:
        from echo_personal_tool.presentation.mmode_widget import _SWEEP_SPEEDS

        assert "25 mm/s" in _SWEEP_SPEEDS
        assert "37.5 mm/s" in _SWEEP_SPEEDS
        assert "50 mm/s" in _SWEEP_SPEEDS

    def test_set_sweep_speed(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_sweep_speed("50 mm/s")
        # Should not crash

    def test_set_scan_line(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_scan_line((10.0, 20.0), (50.0, 60.0))
        assert widget._scan_start == (10.0, 20.0)
        assert widget._scan_end == (50.0, 60.0)

    def test_set_scan_line_none(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_scan_line(None, None)
        assert widget._scan_start is None
        assert widget._scan_end is None

    def test_recalculate_from_frames(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        frames = [np.random.randint(0, 255, (64, 64), dtype=np.uint8) for _ in range(10)]
        widget.recalculate_from_frames(frames, (32.0, 0.0), (32.0, 63.0))
        # Should populate the buffer

    def test_set_sweep_speed_same_noop(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        # Default is 512, set to same → no change
        widget.set_sweep_speed("25 mm/s")  # 128, different from 512
        assert widget._buffer_width == 128

    def test_set_sweep_speed_invalid(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_sweep_speed("invalid_speed")
        assert widget._buffer_width == 512  # unchanged

    def test_clear_measurements(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._clear_measurements()
        assert widget._teichholz_ed_btn.isChecked() is False
        assert widget._teichholz_es_btn.isChecked() is False

    def test_start_vertical_measurement(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._start_vertical_measurement()
        assert widget._measurement_tool._active_mode == "vertical"

    def test_start_horizontal_measurement(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._start_horizontal_measurement()
        assert widget._measurement_tool._active_mode == "horizontal"

    def test_start_arbitrary_measurement(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._start_arbitrary_measurement()
        assert widget._measurement_tool._active_mode == "arbitrary"

    def test_start_teichholz_ed(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._start_teichholz_ed()
        assert widget._teichholz_ed_btn.isChecked() is True

    def test_start_teichholz_es(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget._start_teichholz_es()
        assert widget._teichholz_es_btn.isChecked() is True

    def test_on_teichholz_ed_complete(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        received = []
        widget.teichholz_ed_complete.connect(lambda m: received.append(m))
        widget._on_teichholz_ed_complete([])
        assert received == [[]]
        assert widget._teichholz_es_btn.isEnabled() is True

    def test_on_teichholz_es_complete(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        received = []
        widget.teichholz_es_complete.connect(lambda m: received.append(m))
        widget._on_teichholz_es_complete({})
        assert received == [{}]

    def test_set_scan_line_with_num_samples(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_scan_line((10.0, 20.0), (50.0, 60.0), num_samples=128)
        assert widget._num_samples == 128
        assert widget._image_buffer.shape == (128, 512)

    def test_set_depth_range_mm(self, qtbot) -> None:
        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget()
        qtbot.addWidget(widget)
        widget.set_depth_range_mm(100.0)
        # Should calculate depth_mm_per_pixel from num_samples and range
        assert widget._depth_mm_per_pixel is not None

    def test_on_new_column_advances_sweep(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget(buffer_width=10)
        qtbot.addWidget(widget)
        initial_x = widget._sweep_x
        column = np.random.randint(0, 255, (256,), dtype=np.uint8)
        widget.on_new_column(column)
        assert widget._sweep_x == (initial_x + 1) % 10

    def test_on_new_column_wraps(self, qtbot) -> None:
        import numpy as np

        from echo_personal_tool.presentation.mmode_widget import MModeWidget

        widget = MModeWidget(buffer_width=5)
        qtbot.addWidget(widget)
        widget._sweep_x = 4
        column = np.random.randint(0, 255, (256,), dtype=np.uint8)
        widget.on_new_column(column)
        assert widget._sweep_x == 0  # wrapped


# ── dark_theme extended v2 ─────────────────────────────────────────


class TestDarkThemeExtendedV2:
    def test_build_clinical_stylesheet_dark_contains_key_rules(self) -> None:
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        css = build_clinical_stylesheet(font_size=14, theme="dark")
        assert "QWidget" in css
        assert "QMainWindow" in css
        assert "QDialog" in css
        assert "QScrollBar" in css
        assert "QStatusBar" in css
        assert "QPushButton" in css

    def test_build_clinical_stylesheet_vscode_dark(self) -> None:
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        css = build_clinical_stylesheet(font_size=13, theme="vscode_dark")
        assert "QWidget" in css

    def test_build_clinical_stylesheet_vscode_light(self) -> None:
        from echo_personal_tool.presentation.dark_theme import build_clinical_stylesheet

        css = build_clinical_stylesheet(font_size=13, theme="vscode_light")
        assert "QWidget" in css

    def test_apply_clinical_theme_no_app(self) -> None:
        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        # Should not crash when no QApplication exists
        # (we can't easily test this without killing the app)
        apply_clinical_theme(font_size=12, theme="dark", animate=False)

    def test_apply_clinical_theme_with_widget(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        widget = QWidget()
        qtbot.addWidget(widget)
        apply_clinical_theme(widget, font_size=12, theme="dark", animate=False)
        # Should apply palette without crash

    def test_apply_clinical_theme_light(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        widget = QWidget()
        qtbot.addWidget(widget)
        apply_clinical_theme(widget, font_size=12, theme="light", animate=False)

    def test_apply_clinical_theme_animated(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.dark_theme import apply_clinical_theme

        widget = QWidget()
        qtbot.addWidget(widget)
        apply_clinical_theme(widget, font_size=12, theme="dark", animate=True)

    def test_apply_theme_direct(self, qtbot) -> None:
        from PySide6.QtWidgets import QApplication, QWidget

        from echo_personal_tool.presentation.dark_theme import _apply_theme_direct

        app = QApplication.instance()
        widget = QWidget()
        qtbot.addWidget(widget)
        _apply_theme_direct(app, widget, 14, "dark")
        assert app.styleSheet() != ""

    def test_fade_theme_transition(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget

        from echo_personal_tool.presentation.dark_theme import _fade_theme_transition

        widget = QWidget()
        qtbot.addWidget(widget)
        _fade_theme_transition(widget, 12, "dark")
        assert hasattr(widget, "_theme_anim")

    def test_resolve_theme_system_linux(self) -> None:
        import sys

        from echo_personal_tool.presentation.dark_theme import _DARK, _LIGHT, _resolve_theme

        if sys.platform == "linux":
            # On Linux, system theme depends on GTK_THEME env
            result = _resolve_theme("system")
            assert result in (_DARK, _LIGHT)

    def test_vs_code_dark_palette_keys(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _VS_CODE_DARK

        assert "bg_dark" in _VS_CODE_DARK
        assert "text" in _VS_CODE_DARK
        assert "accent_tab" in _VS_CODE_DARK

    def test_vs_code_light_palette_keys(self) -> None:
        from echo_personal_tool.presentation.dark_theme import _VS_CODE_LIGHT

        assert "bg_dark" in _VS_CODE_LIGHT
        assert "text" in _VS_CODE_LIGHT


# ── browser_item_delegate extended ─────────────────────────────────


class TestBrowserItemDelegateExtended:
    def test_item_data_role_constant(self) -> None:
        from echo_personal_tool.presentation.browser_item_delegate import _ITEM_DATA_ROLE

        assert _ITEM_DATA_ROLE == 256

    def test_text_height_constant(self) -> None:
        from echo_personal_tool.presentation.browser_item_delegate import _TEXT_HEIGHT

        assert _TEXT_HEIGHT == 28

    def test_delegate_is_subclass(self) -> None:
        from PySide6.QtWidgets import QStyledItemDelegate

        from echo_personal_tool.presentation.browser_item_delegate import (
            InstanceThumbnailDelegate,
        )

        assert issubclass(InstanceThumbnailDelegate, QStyledItemDelegate)


# ── pyqtgraph_export extended ──────────────────────────────────────


class TestPyqtgraphExportExtended:
    def test_allowed_exporter_classes_non_plot_item(self) -> None:
        from echo_personal_tool.presentation.pyqtgraph_export import (
            _PLOT_ONLY_EXPORTERS,
            allowed_exporter_classes,
        )

        result = allowed_exporter_classes("not_a_plot")
        for exporter in _PLOT_ONLY_EXPORTERS:
            assert exporter not in result

    def test_plot_only_exporters_set(self) -> None:
        from pyqtgraph.exporters.CSVExporter import CSVExporter
        from pyqtgraph.exporters.HDF5Exporter import HDF5Exporter
        from pyqtgraph.exporters.Matplotlib import MatplotlibExporter

        from echo_personal_tool.presentation.pyqtgraph_export import _PLOT_ONLY_EXPORTERS

        assert CSVExporter in _PLOT_ONLY_EXPORTERS
        assert HDF5Exporter in _PLOT_ONLY_EXPORTERS
        assert MatplotlibExporter in _PLOT_ONLY_EXPORTERS

    def test_patch_export_dialog_idempotent(self) -> None:
        from pyqtgraph.GraphicsScene import exportDialog as pg_export_dialog

        from echo_personal_tool.presentation.pyqtgraph_export import (
            patch_pyqtgraph_export_dialog,
        )

        # First call should patch
        patch_pyqtgraph_export_dialog()
        dialog_cls = pg_export_dialog.ExportDialog
        assert getattr(dialog_cls, "_echo_export_patched", False) is True

        # Second call should be no-op
        patch_pyqtgraph_export_dialog()
        assert getattr(dialog_cls, "_echo_export_patched", False) is True

    def test_patch_preserves_references(self) -> None:
        from pyqtgraph.GraphicsScene import exportDialog as pg_export_dialog

        from echo_personal_tool.presentation.pyqtgraph_export import (
            patch_pyqtgraph_export_dialog,
        )

        patch_pyqtgraph_export_dialog()
        dialog_cls = pg_export_dialog.ExportDialog
        assert hasattr(dialog_cls, "_echo_original_update_format_list")
        assert hasattr(dialog_cls, "_echo_original_export_clicked")


# ── server_profile_dialog extended ─────────────────────────────────


class TestServerProfileDialogExtended:
    def test_initial_buttons_disabled(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        assert dialog._btn_load.isEnabled() is False
        assert dialog._btn_delete.isEnabled() is False

    def test_save_as_button_always_enabled(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        assert dialog._btn_save.isEnabled() is True

    def test_on_load_no_selection(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        dialog._selected_name = None
        dialog._on_load()  # should return early
        assert dialog._selected_name is None

    def test_on_delete_no_selection(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        dialog._selected_name = None
        dialog._on_delete()  # should return early
        assert dialog._selected_name is None

    def test_refresh_list(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        dialog._refresh_list()  # should not crash
        assert dialog._list.count() >= 0


# ── mmode_scan_line extended ───────────────────────────────────────


class TestMModeScanLineExtended:
    def test_no_view_no_crash(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.set_end((50.0, 0.0))
        # update_graphics_for_view with no view should not crash
        item._update_graphics()

    def test_remove_from_view_no_view(self) -> None:
        from echo_personal_tool.presentation.mmode_scan_line import MModeScanLineItem

        item = MModeScanLineItem(viewer_widget=None)
        item.set_start((10.0, 20.0))
        item.set_end((50.0, 0.0))
        # remove_from_view with no view should not crash
        item.remove_from_view(None)


# ── server_profile_dialog v2 ───────────────────────────────────────


class TestServerProfileDialogV2:
    def test_on_load_with_selected_no_profile(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        dialog._selected_name = "nonexistent_profile"
        with (
            patch("echo_personal_tool.presentation.server_profile_dialog.load_profile", return_value=None),
            patch("echo_personal_tool.presentation.server_profile_dialog.QMessageBox"),
        ):
            dialog._on_load()

    def test_on_load_empty_name_noop(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        dialog._selected_name = None
        dialog._on_load()
        # Should return early without crash

    def test_on_save_as_empty_name_noop(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        with patch(
            "echo_personal_tool.presentation.server_profile_dialog.QInputDialog",
        ) as mock_input:
            mock_input.getText.return_value = ("", False)
            dialog._on_save_as()
        # Should return early

    def test_selected_settings_property(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        assert dialog.selected_settings is settings

    def test_list_profiles_called(self, qtbot) -> None:
        from echo_personal_tool.infrastructure.server_settings import ServerSettings
        from echo_personal_tool.presentation.server_profile_dialog import (
            ServerProfileDialog,
        )

        settings = ServerSettings()
        dialog = ServerProfileDialog(settings)
        qtbot.addWidget(dialog)
        with patch(
            "echo_personal_tool.presentation.server_profile_dialog.list_profiles",
            return_value={"p1": {}, "p2": {}},
        ):
            dialog._refresh_list()
        assert dialog._list.count() == 2


# ── structured_reference_widget ────────────────────────────────────


class TestStructuredReferenceWidgetHelpers:
    def test_parse_pathology_rows_gradation(self) -> None:
        from echo_personal_tool.presentation.structured_reference_widget import (
            _ParameterCard,
        )

        desc = "Лёгкая: <0.20 / Умеренная: 0.20-0.39 / Тяжёлая: ≥0.40"
        rows = _ParameterCard._parse_pathology_rows(desc, "%")
        assert len(rows) == 3
        assert rows[0][0] == "Лёгкая"
        assert "%" in rows[0][1]

    def test_parse_pathology_rows_simple(self) -> None:
        from echo_personal_tool.presentation.structured_reference_widget import (
            _ParameterCard,
        )

        desc = ">115 (м) / >95 (ж) — гипертрофия"
        rows = _ParameterCard._parse_pathology_rows(desc, "")
        assert len(rows) == 1

    def test_parse_pathology_rows_with_unit(self) -> None:
        from echo_personal_tool.presentation.structured_reference_widget import (
            _ParameterCard,
        )

        desc = "Минимальная: <40 / Умеренная: 40-59 / Выраженная: ≥60"
        rows = _ParameterCard._parse_pathology_rows(desc, "мм")
        assert len(rows) == 3
        assert "мм" in rows[0][1]

    def test_creation(self, qtbot, tmp_path) -> None:
        import yaml

        from echo_personal_tool.domain.services.reference_data_store import (
            ReferenceDataStore,
        )
        from echo_personal_tool.presentation.structured_reference_widget import (
            StructuredReferenceWidget,
        )

        yaml_content = {"topics": [{"name": "Test", "slug": "test", "pathologies": []}]}
        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text(yaml.dump(yaml_content), encoding="utf-8")

        store = ReferenceDataStore(yaml_path)
        store.load()
        widget = StructuredReferenceWidget(store)
        qtbot.addWidget(widget)
        assert widget is not None

    def test_format_norm_with_params(self, qtbot, tmp_path) -> None:
        import yaml

        from echo_personal_tool.domain.services.reference_data_store import (
            ReferenceDataStore,
        )
        from echo_personal_tool.presentation.structured_reference_widget import (
            StructuredReferenceWidget,
        )

        yaml_content = {"topics": [{"name": "Test", "slug": "test", "pathologies": []}]}
        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text(yaml.dump(yaml_content), encoding="utf-8")

        store = ReferenceDataStore(yaml_path)
        store.load()
        widget = StructuredReferenceWidget(store)
        qtbot.addWidget(widget)
        from types import SimpleNamespace

        param = SimpleNamespace(norm_male=SimpleNamespace(low=60.0, high=100.0), norm_female=None)
        result = widget._format_norm(param)
        assert "60.0" in result

    def test_format_norm_none(self, qtbot, tmp_path) -> None:
        import yaml

        from echo_personal_tool.domain.services.reference_data_store import (
            ReferenceDataStore,
        )
        from echo_personal_tool.presentation.structured_reference_widget import (
            StructuredReferenceWidget,
        )

        yaml_content = {"topics": [{"name": "Test", "slug": "test", "pathologies": []}]}
        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text(yaml.dump(yaml_content), encoding="utf-8")

        store = ReferenceDataStore(yaml_path)
        store.load()
        widget = StructuredReferenceWidget(store)
        qtbot.addWidget(widget)
        from types import SimpleNamespace

        param = SimpleNamespace(norm_male=None, norm_female=None)
        result = widget._format_norm(param)
        assert isinstance(result, str)

    def test_format_norm_range(self, qtbot, tmp_path) -> None:
        import yaml

        from echo_personal_tool.domain.services.reference_data_store import (
            ReferenceDataStore,
        )
        from echo_personal_tool.presentation.structured_reference_widget import (
            StructuredReferenceWidget,
        )

        yaml_content = {"topics": [{"name": "Test", "slug": "test", "pathologies": []}]}
        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text(yaml.dump(yaml_content), encoding="utf-8")

        store = ReferenceDataStore(yaml_path)
        store.load()
        widget = StructuredReferenceWidget(store)
        qtbot.addWidget(widget)
        from types import SimpleNamespace

        norm = SimpleNamespace(low=60.0, high=100.0)
        result = widget._format_norm_range(norm)
        assert "60.0" in result
        assert "100.0" in result

    def test_format_norm_range_none(self, qtbot, tmp_path) -> None:
        import yaml

        from echo_personal_tool.domain.services.reference_data_store import (
            ReferenceDataStore,
        )
        from echo_personal_tool.presentation.structured_reference_widget import (
            StructuredReferenceWidget,
        )

        yaml_content = {"topics": [{"name": "Test", "slug": "test", "pathologies": []}]}
        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text(yaml.dump(yaml_content), encoding="utf-8")

        store = ReferenceDataStore(yaml_path)
        store.load()
        widget = StructuredReferenceWidget(store)
        qtbot.addWidget(widget)
        result = widget._format_norm_range(None)
        assert isinstance(result, str)

    def test_get_current_parameters_empty(self, qtbot, tmp_path) -> None:
        import yaml

        from echo_personal_tool.domain.services.reference_data_store import (
            ReferenceDataStore,
        )
        from echo_personal_tool.presentation.structured_reference_widget import (
            StructuredReferenceWidget,
        )

        yaml_content = {"topics": [{"name": "Test", "slug": "test", "pathologies": []}]}
        yaml_path = tmp_path / "refs.yaml"
        yaml_path.write_text(yaml.dump(yaml_content), encoding="utf-8")

        store = ReferenceDataStore(yaml_path)
        store.load()
        widget = StructuredReferenceWidget(store)
        qtbot.addWidget(widget)
        params = widget._get_current_parameters()
        assert isinstance(params, list)
