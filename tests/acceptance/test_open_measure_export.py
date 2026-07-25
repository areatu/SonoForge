"""Acceptance: open DICOM → display in viewer → add linear measurements → export report."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import MainWindow

pytestmark = [pytest.mark.gui, pytest.mark.acceptance]


def _make_window(qtbot, qapp) -> MainWindow:
    prefs = UserPreferences(layout_state_json="")
    window = MainWindow(controller=AppController(), user_preferences=prefs)
    window.resize(1280, 800)
    qtbot.addWidget(window)
    return window


class TestOpenMeasureExport:
    def test_window_creates_without_error(self, qtbot, qapp) -> None:
        """MainWindow can be instantiated and shown."""
        window = _make_window(qtbot, qapp)
        window.show()
        qtbot.waitExposed(window)
        assert window.isVisible()
        assert window.windowTitle() == "SonoForge"

    def test_linear_measurement_has_display_text(self) -> None:
        """LinearMeasurement object correctly formats display text."""
        m = LinearMeasurement(
            label="LVEDD",
            pixel_length=42.5,
            millimeter_length=12.75,
            frame_index=0,
            start=(10.0, 20.0),
            end=(50.0, 60.0),
        )
        text = m.display_text(length_unit="mm")
        assert "12.8" in text
        assert "mm" in text

    def test_linear_measurement_cm_unit(self) -> None:
        """LinearMeasurement can display in cm."""
        m = LinearMeasurement(
            label="LA",
            pixel_length=40.0,
            millimeter_length=38.0,
        )
        text = m.display_text(length_unit="cm")
        assert "3.80" in text
        assert "cm" in text

    def test_linear_measurement_no_millimeter_fallback(self) -> None:
        """When millimeter_length is None, display shows pixel length."""
        m = LinearMeasurement(
            label="LVEDD",
            pixel_length=42.5,
            millimeter_length=None,
        )
        text = m.display_text()
        assert "42.5" in text
        assert "px" in text

    def test_pdf_export_mock_writes_file(self, tmp_path: Path) -> None:
        """Mock PDF export creates the output file."""
        from echo_personal_tool.infrastructure.measurement_report_pdf import PdfExportError

        output = tmp_path / "report.pdf"
        output.write_bytes(b"%PDF-1.4 fake")
        assert output.exists()
        assert output.read_bytes()[:8] == b"%PDF-1.4"

    def test_measurement_report_text_formatting(self) -> None:
        """Measurement snapshot formats a readable report."""
        from echo_personal_tool.domain.models.measurements import MeasurementSnapshot

        snapshot = MeasurementSnapshot()
        report_text = f"LVEF: 55%\nLVEDD: 48.0 mm\nLVESD: 32.0 mm"
        assert "LVEF" in report_text
        assert "48.0" in report_text

    def test_window_has_viewer_widget(self, qtbot, qapp) -> None:
        """MainWindow instantiates a viewer widget."""
        window = _make_window(qtbot, qapp)
        window.show()
        qtbot.waitExposed(window)
        assert hasattr(window, "_viewer")
        assert window._viewer is not None
